# Changelog

Todas as mudanças notáveis neste projeto serão documentadas neste arquivo.

O formato é baseado no [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/),
e este projeto adere ao [Versionamento Semântico](https://semver.org/lang/pt-BR/).

## [Unreleased]

### Adicionado
- Estrutura de testes automatizados com pytest
- CI/CD pipeline com GitHub Actions
- Arquivo LICENSE (MIT)
- pyproject.toml com configurações de ruff e mypy
- CONTRIBUTING.md e CHANGELOG.md
- Tool `resource_snapshot` com psutil para CPU, RAM, I/O de disco e rede
- Memória operacional em SQLite para fatos recentes da sessão
- Tools nativas D-Bus com pydbus para serviços, NetworkManager, GNOME e status de pacotes
- Faixa visual de recursos na UI com tema inspirado no Yaru/Ubuntu

### Segurança
- Detecção de subshell/backtick na camada de segurança
- Rate limiting no grafo do agente
- Limpeza segura de memória no Vault
- Revalidação de retentativas self-healing antes de executar comandos corrigidos
- Classificação read-only mais restrita para redirecionamentos, pipes mutáveis e flags como `find -delete`

## [0.1.0] - 2026-04-28

### Adicionado
- Tradução de linguagem natural para Bash via LLM local (Ollama)
- Grafo LangGraph com fluxo determinístico
- Camada de segurança com classificação tríplice (READ_ONLY, NEEDS_CONFIRMATION, BLOCKED)
- Auto-avaliação (self-healing) com retry loop
- Interface CustomTkinter com tema Catppuccin
- Contexto de sistema injetado (diretórios XDG, locale, hardware)
- Vault in-memory para senha sudo
- Histórico de comandos em SQLite
- Sistema de logging com rotação diária
- Script run.sh com health check do LLM
- Gerenciamento dinâmico de modelos do Ollama via UI
