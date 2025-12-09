#Script implantado por Ruan Bastos - 01/11/2025
import configparser
import logging
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta # type: ignore
import db_handler as db

# --- Configuração do Logging ---
logging.basicConfig(
    filename='log_preventivas.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# --- Funções de Lógica de Negócio (Passos) ---

def sync_preventives_status(connection):
    """
    Sincroniza o status (ativo/inativo) das preventivas existentes
    com base no status do bem (glpi_plugin_genericobject_gerals.states_id).
    """
    logging.info("--- Iniciando Fase de Manutenção: Sincronizando status das preventivas ---")
    
    # Desativa preventivas de bens que não estão mais ativos (states_id != 1)
    deactivate_query = """
        UPDATE glpi_ticketrecurrents r
        JOIN glpi_plugin_genericobject_gerals g ON g.otherserial = SUBSTRING_INDEX(r.name, 'PL:', -1)
        SET r.is_active = 0
        WHERE g.states_id != 1 AND r.is_active = 1;
    """
    logging.info("Verificando preventivas para DESATIVAR...")
    db.execute_update(connection, deactivate_query)

    # Reativa preventivas de bens que voltaram a ficar ativos (states_id = 1)
    reactivate_query = """
        UPDATE glpi_ticketrecurrents r
        JOIN glpi_plugin_genericobject_gerals g ON g.otherserial = SUBSTRING_INDEX(r.name, 'PL:', -1)
        SET r.is_active = 1
        WHERE g.states_id = 1 AND r.is_active = 0;
    """
    logging.info("Verificando preventivas para REATIVAR...")
    db.execute_update(connection, reactivate_query)
    logging.info("--- Fim da Fase de Manutenção ---")

def get_bens_por_categoria(connection, categoria_id):
    """(Passo 1) Busca todos os bens ATIVOS e suas informações para uma dada categoria."""
    query = """
        SELECT
            b.id,
            b.entities_id,
            b.otherserial,
            b.states_id,
            b.name as bem_name,
            e.name as entity_name
        FROM glpi_plugin_genericobject_gerals as b
        JOIN glpi_entities as e ON b.entities_id = e.id
        WHERE 
            b.plugin_genericobject_geralcategories_id = %s
            AND b.states_id = 1
    """
    return db.fetch_all(connection, query, (categoria_id,))

def create_or_get_category(connection, table_name, parent_id_column, parent_id, category_name, level, extra_fields=None):
    """Função genérica para criar ou obter categorias (ITIL ou Tarefa)."""
    # Verifica se a categoria já existe
    check_query = f"SELECT id FROM {table_name} WHERE name = %s AND {parent_id_column} = %s"
    existing_category = db.fetch_one(connection, check_query, (category_name, parent_id))
    if existing_category:
        logging.info(f"Categoria '{category_name}' já existe na tabela {table_name}. ID: {existing_category['id']}.")
        return existing_category['id']

    # Se não existir, cria
    logging.info(f"Criando categoria '{category_name}' na tabela {table_name}...")
    parent_completename_query = f"SELECT completename FROM {table_name} WHERE id = %s"
    parent = db.fetch_one(connection, parent_completename_query, (parent_id,))
    parent_completename = parent['completename'] if parent else ''
    completename = f"{parent_completename} > {category_name}"

    fields = {
        'entities_id': 0, 'is_recursive': 1, 'name': category_name,
        'completename': completename, 'level': level, 'date_mod': datetime.now(),
        'date_creation': datetime.now(), parent_id_column: parent_id
    }
    if extra_fields:
        fields.update(extra_fields)

    columns = ', '.join(fields.keys())
    placeholders = ', '.join(['%s'] * len(fields))
    insert_query = f"INSERT INTO {table_name} ({columns}) VALUES ({placeholders})"

def create_or_get_task_templates(connection, preventiva, task_category_id):
    """(Passo 4) Cria ou obtém os modelos de tarefa a partir da string de tarefas."""
    task_template_ids = []
    tarefas = [t.strip() for t in preventiva['tarefas'].split(';') if t.strip()]
    
    for tarefa_content in tarefas:
        name = f"Tarefa - {preventiva['categoria_name']}"

        check_query = """
            SELECT id FROM glpi_tasktemplates 
            WHERE name = %s AND content = %s
        """
        existing_template = db.fetch_one(connection, check_query, (name, tarefa_content))
        
        if existing_template:
            logging.info(f"Modelo de tarefa '{name}' com conteúdo '{tarefa_content[:30]}...' já existe. ID: {existing_template['id']}")
            task_template_ids.append(existing_template['id'])
            continue

        # Se não existir, cria
        logging.info(f"Criando modelo de tarefa: '{name}'")
        insert_query = """
            INSERT INTO glpi_tasktemplates (entities_id, is_recursive, name, content, taskcategories_id, date_mod, date_creation, state, users_id_tech)
            VALUES (0, 1, %s, %s, %s, %s, %s, 1, 0)
        """
        new_id = db.execute_insert(connection, insert_query, (name, tarefa_content, task_category_id, datetime.now(), datetime.now()))
        if new_id:
            task_template_ids.append(new_id)
            
    return task_template_ids

def create_or_get_ticket_template(connection, preventiva, bem):
    """(Passo 5) Cria ou obtém o modelo de chamado."""
    template_name = f"Preventiva - {preventiva['categoria_name']} - {bem['entity_name']} - PL:{bem['otherserial']}"
    
    check_query = "SELECT id FROM glpi_tickettemplates WHERE name = %s AND entities_id = %s"
    existing_template = db.fetch_one(connection, check_query, (template_name, bem['entities_id']))
    
    if existing_template:
        logging.info(f"Modelo de chamado '{template_name}' já existe. ID: {existing_template['id']}")
        return existing_template['id'], False # Retorna ID e "não foi criado agora"
    
    logging.info(f"Criando modelo de chamado: '{template_name}'")
    insert_query = "INSERT INTO glpi_tickettemplates (name, entities_id) VALUES (%s, %s)"
    new_id = db.execute_insert(connection, insert_query, (template_name, bem['entities_id']))
    return new_id, True # Retorna ID e "foi criado agora"

def configure_ticket_template(connection, template_id, itil_category_id, task_ids, preventiva, bem, config):
    """(Passos 6, 7, 8) Configura os campos do modelo de chamado recém-criado."""
    logging.info(f"Configurando campos para o modelo de chamado ID: {template_id}")

    # Passo 6: Campos Ocultos
    hidden_fields = config['glpi_defaults']['campos_ocultos'].split(',')
    for field_num in hidden_fields:
        db.execute_insert(connection, "INSERT INTO glpi_tickettemplatehiddenfields (tickettemplates_id, num) VALUES (%s, %s)", (template_id, int(field_num)))

    # Passo 7: Campos Obrigatórios
    mandatory_fields = config['glpi_defaults']['campos_obrigatorios'].split(',')
    for field_num in mandatory_fields:
        db.execute_insert(connection, "INSERT INTO glpi_tickettemplatemandatoryfields (tickettemplates_id, num) VALUES (%s, %s)", (template_id, int(field_num)))
    
    # Passo 8: Campos Pré-definidos
    title = f"Preventiva - {preventiva['categoria_name']} - PL:{bem['otherserial']}"
    nome_do_bem = bem['bem_name']
    base_descricao = config['script_settings']['descricao_chamado']
    nova_descricao = f"Bem:{nome_do_bem}\n\n{base_descricao}"
    predefined_fields = {
        1: title,  # Título
        12: config['glpi_defaults']['ticket_status_id'], # Status
        83: config['glpi_defaults']['location_id'], # Localização
        14: config['glpi_defaults']['ticket_type_id'], # Tipo
        7: itil_category_id, # Categoria
        21: nova_descricao, # Descrição
        4: config['glpi_defaults']['requester_user_id'], # Requerente
        13: f"PluginGenericobjectGeral_{bem['id']}" # Bem atrelado
    }
    for num, value in predefined_fields.items():
        db.execute_insert(connection, "INSERT INTO glpi_tickettemplatepredefinedfields (tickettemplates_id, num, value) VALUES (%s, %s, %s)", (template_id, num, value))
    
    # Tarefas (campo 175) - uma linha por tarefa
    for task_id in task_ids:
        db.execute_insert(connection, "INSERT INTO glpi_tickettemplatepredefinedfields (tickettemplates_id, num, value) VALUES (%s, 175, %s)", (template_id, task_id))

def create_recurrent_ticket(connection, template_id, preventiva, bem, config):
    """(Passo 9) Cria o chamado recorrente final."""
    recurrent_name = f"Preventiva - {preventiva['categoria_name']} - PL:{bem['otherserial']}"
    logging.info(f"Criando chamado recorrente: '{recurrent_name}'")
    
    try:
        dia_alvo = int(config['glpi_defaults']['dia_inicio_preventiva'])
    except ValueError:
        logging.warning("Valor de 'dia_inicio_preventiva' inválido no config.ini. Usando dia 1 como padrão.")
        dia_alvo = 1

    now = datetime.now() 
    first_day_this_month = now.replace(day=1)
    first_day_next_month = first_day_this_month + relativedelta(months=1)
    
    try:
        target_date = first_day_next_month.replace(day=dia_alvo, hour=8, minute=0, second=0, microsecond=0)
    except ValueError:
        logging.warning(f"Dia {dia_alvo} é inválido para o próximo mês. Usando o último dia do mês.")
        last_day_next_month = first_day_next_month + relativedelta(months=1) - relativedelta(days=1)
        target_date = last_day_next_month.replace(hour=8, minute=0, second=0, microsecond=0)
    
    begin_date_dt = target_date.strftime('%Y-%m-%d %H:%M:%S')
      
    insert_query = """
        INSERT INTO glpi_ticketrecurrents (name, entities_id, is_active, tickettemplates_id, begin_date, periodicity, calendars_id, next_creation_date)
        VALUES (%s, %s, 1, %s, %s, %s, %s, %s)
    """

    db.execute_insert(connection, insert_query, (
        recurrent_name, 
        bem['entities_id'], 
        template_id, 
        begin_date_dt, 
        preventiva['periodo'], 
        config['glpi_defaults']['calendar_id'],
        begin_date_dt
    ))

# --- Função Principal ---

def main():
    """Função principal que orquestra todo o processo."""
    logging.info("=============================================")
    logging.info("Iniciando script de criação de preventivas...")
    
    config = configparser.ConfigParser()
    config.read('config.ini')
    
    connection = db.connect_db(config)
    if not connection:
        logging.error("Não foi possível conectar ao banco de dados. Abortando.")
        return

    try:
        # Desativa ou ativa bens de acordo com o states_id
        sync_preventives_status(connection)

        # Busca todas as regras de preventiva
        logging.info("--- Iniciando Fase de Criação: Verificando novas preventivas ---")
        preventivas_rules = db.fetch_all(connection, "SELECT * FROM preventivas")
        logging.info(f"Encontradas {len(preventivas_rules)} regras na tabela 'preventivas'.")


        for preventiva in preventivas_rules:
            logging.info(f"--- Processando regra para categoria: '{preventiva['categoria_name']}' ---")
            
            bens_a_processar = get_bens_por_categoria(connection, preventiva['categoria_id'])
            if not bens_a_processar:
                logging.warning(f"Nenhum bem Ativo encontrado para a categoria ID {preventiva['categoria_id']}.")
                continue

            logging.info(f"Encontrados {len(bens_a_processar)} bens para esta categoria.")
            
            # (Passo 2 e 3) Cria categorias de forma centralizada antes do loop de bens
            itil_cat_id = create_or_get_category(connection, 'glpi_itilcategories', 'itilcategories_id', config['glpi_defaults']['id_cat_itil_preventiva'], preventiva['categoria_name'], 2, {'is_helpdeskvisible': 0, 'is_request': 1})
            task_cat_id = create_or_get_category(connection, 'glpi_taskcategories', 'taskcategories_id', config['glpi_defaults']['id_cat_task_preventiva'], preventiva['categoria_name'], 2, {'is_active': 1})


            if not itil_cat_id or not task_cat_id:
                logging.error(f"Não foi possível criar/obter categorias para '{preventiva['categoria_name']}'. Pulando esta regra.")
                continue

            # (Passo 4) Cria modelos de tarefa
            task_template_ids = create_or_get_task_templates(connection, preventiva, task_cat_id)

            for bem in bens_a_processar:
                logging.info(f"Processando bem ID: {bem['id']} da Loja: '{bem['entity_name']}'")
                
                # VERIFICAÇÃO PRINCIPAL: O chamado recorrente já existe?
                recurrent_name_check = f"Preventiva - {preventiva['categoria_name']} - PL:{bem['otherserial']}"
                check_query = "SELECT id FROM glpi_ticketrecurrents WHERE name = %s"
                if db.fetch_one(connection, check_query, (recurrent_name_check,)):
                    logging.info(f"Preventiva para o bem com plaqueta {bem['otherserial']} já existe e está ativa. Pulando.")
                    continue

                # (Passo 5)
                ticket_template_id, was_created = create_or_get_ticket_template(connection, preventiva, bem)


                if not ticket_template_id:
                    logging.error(f"Falha ao criar/obter modelo de chamado para o bem com plaqueta {bem['otherserial']}. Pulando este bem.")
                    continue
                
                # (Passo 6, 7, 8) Só configura se o modelo foi recém-criado
                if was_created:
                    configure_ticket_template(connection, ticket_template_id, itil_cat_id, task_template_ids, preventiva, bem, config)
                
                # (Passo 9)
                create_recurrent_ticket(connection, ticket_template_id, preventiva, bem, config)

    finally:
        db.close_db(connection)
        logging.info("Script finalizado.")
        logging.info("=============================================\n")


if __name__ == "__main__":
    main()