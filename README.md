# 🐧 Ubuntu Agent

> Um assistente de desktop nativo para Ubuntu 24.04 que traduz linguagem natural em comandos Bash seguros e executa tarefas do sistema operacional usando Inteligência Artificial local.

O **Ubuntu Agent** é um utilitário de sistema projetado para simplificar a administração e o uso do Linux. Através de uma interface limpa (construída com CustomTkinter) acionada por atalho global, você pode pedir ao sistema para realizar tarefas complexas em português ("instale o Spotify", "limpe o cache do sistema", "crie um script de backup"), e o agente traduzirá isso para comandos Bash precisos.

Toda a inteligência roda **100% localmente** através do [Ollama](https://ollama.com/), garantindo total privacidade — nenhum dado do seu sistema é enviado para a nuvem.

---

## ✨ Principais Funcionalidades

- **Tradução de Linguagem Natural para Bash:** Peça o que você quer fazer e o LLM gera o comando adequado usando variáveis de ambiente corretas (suporta multi-idioma e mapeamento de diretórios do sistema).
- **Auto-Correção e Avaliação (Self-Healing):** Se um comando bash ou ferramenta nativa falhar (ex: falta de dependência ou erro de execução), o agente detecta a falha e pede ao LLM para corrigir e tentar uma alternativa de forma autônoma.
- **Camada de Segurança Rígida:**
  - Comandos *read-only* (como `ls`, `cat`, `df`) rodam direto.
  - Comandos de mutação (como `apt install`, `rm`, `chmod`) exigem **confirmação explícita do usuário** em um modal seguro.
  - Blocklist nativa impede comandos destrutivos perigosos (ex: `rm -rf /`, `chmod -R 777`).
- **Contexto e Memória:** O agente lembra dos últimos comandos enviados na mesma sessão (via banco de dados SQLite embutido).
- **Consciência de Recursos:** Antes de rotear uma ação, o grafo coleta um snapshot *read-only* de CPU, RAM, I/O de disco e rede com `psutil`, permitindo evitar tarefas pesadas quando a máquina já está saturada.
- **Memória Operacional:** Além do histórico bruto, o SQLite guarda fatos úteis de curto/médio prazo, como pacotes instalados e serviços manipulados recentemente.
- **Ferramentas Nativas D-Bus:** Para serviços, rede, GNOME e status de pacotes, o agente prioriza tools nativas via `pydbus` antes de recorrer a Bash.
- **Sem Interrupções:** Executa aplicativos gráficos com `nohup` em background para não travar o processo principal.
- **UI Dinâmica e Responsiva:**
  - **Modo Spotlight:** O agente inicia em um formato minimalista (apenas uma barra de busca), focado na entrada do comando inicial.
  - **Expansão Inteligente:** Após o primeiro uso, a interface se expande suavemente no estilo Web-Chat, revelando logs, configurações e o andamento do LLM.
  - **Temas Nativos:** Adapta-se automaticamente ao tema do sistema (Claro/Escuro) utilizando suporte nativo do CustomTkinter, com opção de ajuste manual.
  - **Responsividade:** Layout centralizado e confortável, ideal para uso minimizado ou em tela cheia.

---

## 🏗️ Arquitetura

O projeto utiliza **LangGraph** para criar um fluxo de execução determinístico e seguro:

1. **Input do Usuário:** Recebido via interface gráfica.
2. **Contexto:** Injeção das variáveis de ambiente (`$DESKTOP`, `$DOCUMENTS`, etc.) baseadas na máquina do usuário local (`xdg-user-dir`).
3. **Resource Tool:** Snapshot JSON *read-only* de CPU, RAM, I/O de disco e rede é injetado no prompt.
4. **Operational Memory:** Memórias recentes do SQLite são reinjetadas para manter continuidade da sessão.
5. **LLM Router:** O modelo gera um bloco Markdown `tool` para ações nativas ou `bash` como fallback.
6. **Native Tools:** Tools D-Bus executam leituras e ações nativas com degradação controlada quando o serviço alvo não responde.
7. **Safety Validator:** Regex e análise estática classificam comandos Bash como `READ_ONLY`, `NEEDS_CONFIRMATION` ou `BLOCKED`.
8. **Executor:** Roda subprocessos de forma isolada, capturando `stdout` e `stderr`, com tratamento inteligente de timeout para comandos `sudo` sem senha.
9. **Evaluation Node:** Um segundo prompt avalia o `exit_code` e a saída. Se o resultado não satisfizer o objetivo inicial ou uma ferramenta falhar, o grafo faz um *loop* (máximo 2 vezes) com feedback do erro para o LLM gerar uma correção (como um fallback em Bash).

---

## 🚀 Requisitos

- **Sistema Operacional:** Ubuntu 24.04 LTS (ou derivado)
- **Python:** 3.12+
- **Dependências de Sistema:**
  - `python3-venv` e `python3-tk`
  - `python3-gi`, `libdbus-1-dev`, `libgirepository1.0-dev`, `gir1.2-gtk-3.0` e `gir1.2-networkmanager-1.0` (para integração D-Bus/GTK/NetworkManager)
- **Motor de IA Local:** [Ollama](https://ollama.com/) instalado e rodando.

---

## ⚙️ Instalação

1. **Clone o repositório:**
   ```bash
   git clone https://github.com/seu-usuario/IA_agentica_ubuntu.git
   cd IA_agentica_ubuntu
   ```

2. **Certifique-se de ter o Ollama instalado:**
   ```bash
   curl -fsSL https://ollama.com/install.sh | sh
   ```

3. **Inicie o agente usando o script gerenciador:**
   O script de execução irá criar o ambiente virtual, instalar dependências do `requirements.txt`, baixar o modelo do Ollama automaticamente e rodar o projeto.
   ```bash
   ./run.sh
   ```

*(O agente usa o modelo `qwen2.5-coder:3b` por padrão, que é leve e altamente otimizado para comandos bash).*

### 📦 Instalação via Snap (Recomendado)

O Ubuntu Agent pode ser instalado facilmente via Snap para maior portabilidade e gerenciamento de dependências:

1. **Construa o snap localmente (requer `snapcraft`):**
   ```bash
   snapcraft
   ```

2. **Instale o pacote gerado:**
   ```bash
   sudo snap install ubuntu-agent_*.snap --classic --dangerous
   ```

3. **Inicie o agente:**
   ```bash
   ubuntu-agent
   ```

---

## ⌨️ Como Usar

Com o aplicativo rodando em segundo plano:
1. Pressione `Super + Space` (ou configure no seu ambiente gráfico apontando para `python3 main.py --toggle`) para invocar a janela principal.
2. Digite sua requisição. Exemplo: *"Atualize os pacotes do sistema"* ou *"Faça um zip da pasta Documentos"*.
3. O agente pensará, exibirá os passos na interface gráfica e, se necessário, abrirá um modal pedindo sua aprovação para executar.

---

## 🔒 Permissões e Segurança
- **Sudo:** Se você enviar comandos que necessitam de `sudo`, o agente abrirá um cofre seguro na própria UI para solicitar sua senha apenas em memória durante a execução do comando.
- **Full Access (Modo Inseguro):** Caso habilitado na interface, desativa todas as confirmações de segurança do LangGraph, executando comandos e ferramentas de mutação de forma 100% autônoma (útil para automação total ou usuários avançados). Falhas neste modo engatilham as mesmas rotinas de auto-recuperação (Self-Healing).

---

## 🛠️ Tecnologias Utilizadas
- [LangChain](https://python.langchain.com/) / [LangGraph](https://python.langchain.com/docs/langgraph)
- [CustomTkinter](https://customtkinter.tomschimansky.com/)
- [SQLite3](https://docs.python.org/3/library/sqlite3.html)
- [Ollama](https://ollama.com/)
- [psutil](https://psutil.readthedocs.io/) para leitura de recursos
- [pydbus](https://github.com/LEW21/pydbus) para integração nativa D-Bus

---

## 📄 Licença
Distribuído sob a licença MIT. Veja `LICENSE` para mais informações.
