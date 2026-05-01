# Contribuindo com o Ubuntu Agent

Obrigado por considerar contribuir com o Ubuntu Agent! 🐧

## Como Contribuir

### Reportar Bugs
1. Verifique se o bug já não foi reportado nas [Issues](../../issues).
2. Abra uma nova issue com o template de bug report.
3. Inclua: versão do Ubuntu, versão do Python, modelo do Ollama, e logs relevantes de `data/logs/agent.log`.

### Sugerir Features
1. Abra uma issue com a tag `enhancement`.
2. Descreva o problema que a feature resolve e a solução proposta.

### Pull Requests
1. Fork o repositório.
2. Crie um branch descritivo: `git checkout -b feat/minha-feature` ou `fix/meu-fix`.
3. Instale as dependências de desenvolvimento:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -e ".[dev]"
   ```
4. Escreva testes para suas mudanças.
5. Rode os checks antes de commitar:
   ```bash
   ruff check src/ tests/
   mypy src/ --ignore-missing-imports
   pytest tests/ --cov=src
   ```
6. Faça commit com mensagens descritivas (convenção [Conventional Commits](https://www.conventionalcommits.org/)):
   - `feat:` nova funcionalidade
   - `fix:` correção de bug
   - `docs:` documentação
   - `test:` testes
   - `refactor:` refatoração
   - `security:` correção de segurança
7. Abra o PR apontando para o branch `main`.

## Ambiente de Desenvolvimento

### Requisitos
- Python 3.12+
- Ubuntu 24.04 LTS (recomendado)
- Ollama instalado e rodando

### Setup rápido
```bash
git clone https://github.com/seu-usuario/IA_agentica_ubuntu.git
cd IA_agentica_ubuntu
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest tests/
```

## Padrões de Código

- **Linting:** `ruff` com configuração do `pyproject.toml`
- **Type hints:** Obrigatórias em funções públicas
- **Docstrings:** Formato Google (já usado no projeto)
- **Idioma do código:** Inglês para nomes de variáveis/funções, Português para docstrings e comentários
- **Testes:** Mínimo de 80% de cobertura em módulos novos

## Segurança

Se você encontrar uma vulnerabilidade de segurança, **NÃO abra uma issue pública**. 
Envie um email para o mantenedor ou use a funcionalidade de Security Advisories do GitHub.
