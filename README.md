# Automação de Manutenção Preventiva para GLPI

Este projeto automatiza a criação de chamados recorrentes de manutenção preventiva no GLPI, com base em categorias de equipamentos e uma tabela de lógica de manutenção, utilizando os objetos cadastrados no GenericObjects

Ele foi projetado para rodar como um serviço agendado (via cron ou systemd) em um servidor Linux, interagindo diretamente com o banco de dados MariaDB/MySQL do GLPI.

## Funcionalidades Principais

* **Sincronização de Status:** Ativa ou desativa preventivas automaticamente com base no status do bem no GLPI (`states_id`).
* **Criação Inteligente:** Cria automaticamente toda a estrutura necessária no GLPI:
    * Categorias de Chamado (ITIL)
    * Categorias de Tarefa
    * Modelos de Tarefa (um para cada item da lista de tarefas)
    * Modelos de Chamado (um por equipamento, com campos pré-definidos)
* **Nomeação Única:** Nomeia os chamados e modelos usando o número de plaqueta do equipamento (`otherserial`) para fácil identificação.
* **Ativação Automática:** Preenche a `next_creation_date` para garantir que o cron do GLPI crie os chamados na data correta.
* **Idempotente:** Pode ser executado repetidamente. Ele só cria o que for novo e só atualiza o que mudou.

## Pré-requisitos de Ambiente (GLPI)

Antes de executar o script, o seu ambiente GLPI **deve** ser preparado:

1.  **Plugin `GenericObject`:** Você precisa ter o plugin **Objetos Genéricos (`genericobject`)** instalado e ativado no seu GLPI.

2.  **Tipo de Objeto:** O script foi escrito para interagir com um tipo de objeto específico. No GLPI (em *Configurar > Objetos Genéricos*), você deve criar um tipo de objeto. O script assume que o nome deste objeto é **"Geral"**, o que resulta na tabela `glpi_plugin_genericobject_gerals`.
    * **Importante:** Se o seu tipo de objeto tiver um nome diferente (ex: "Ativo"), a tabela do banco de dados será outra (ex: `glpi_plugin_genericobject_ativos`), e você precisará ajustar manualmente os nomes das tabelas no script `main.py`.

3.  **Campos Obrigatórios:** Dentro da configuração do seu tipo de objeto "Geral", você deve garantir que os seguintes campos padrão do GLPI estejam ativos e em uso, pois o script depende deles:
    * **`Categoria`** (`plugin_genericobject_geralcategories_id`): Campo essencial que o script usa para vincular o bem à lógica da tabela `preventivas`.
    * **`Status`** (`states_id`): Campo crítico para a lógica de ativação/desativação. O script considera o `ID 1` como "Ativo".
    * **`Nº de Série Alternativo`** (`otherserial`): Campo **fundamental**. O script usa este campo (que você pode usar para a "plaqueta") para nomear todos os chamados e modelos.
    * **`Entidade`** (`entities_id`): Usado para atribuir o chamado e o modelo à entidade/loja correta.

## Estrutura do Projeto

* `main.py`: O orquestrador principal do script.
* `db_handler.py`: Módulo que gerencia todas as conexões e queries com o banco de dados.
* `config.ini.example`: Template de configuração.
* `requirements.txt`: Dependências do Python.
* `/systemd_examples/`: Exemplos de arquivos `.service` e `.timer` para automação no Linux.

## Instalação e Uso

1.  **Clone o Repositório:**
    ```bash
    git clone https://github.com/ravisca/glpi-automacao-preventivas
    cd glpi-automacao-preventivas
    ```

2.  **Crie a Tabela de Lógica:**
    Execute o SQL abaixo no seu banco de dados GLPI (MariaDB) para criar a tabela `preventivas`:
    ```sql
    CREATE TABLE preventivas (
      id INT AUTO_INCREMENT PRIMARY KEY,
      categoria_name VARCHAR(255) NOT NULL,
      categoria_id INT NOT NULL,
      periodo VARCHAR(50),
      tarefas TEXT
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    ```
    *Popule esta tabela com sua lógica de manutenção.*

3.  **Crie um Ambiente Virtual e Instale as Dependências:**
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
    ```

4.  **Configure o Script:**
    Copie o template de configuração e edite-o com seus dados do banco e IDs do GLPI.
    ```bash
    cp config.ini.example config.ini
    nano config.ini
    ```

5.  **Execute o Teste Manual:**
    ```bash
    python3 main.py
    ```
    *Verifique o arquivo `log_preventivas.log` para ver a saída.*

6.  **(Opcional) Configure a Automação com Systemd:**
    * Copie os arquivos de exemplo de `systemd_examples/` para `/etc/systemd/system/`.
    * Edite `preventivas.service` para ajustar o `User=` e `WorkingDirectory=`.
    * Execute `sudo systemctl daemon-reload && sudo systemctl restart preventivas.timer`.