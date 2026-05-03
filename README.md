# Ubuntu AI Agent

Local AI assistant for Ubuntu automation with safety gates, memory and native Linux integrations.

PT-BR: assistente local para automatizar tarefas no Ubuntu com foco em seguranca, controle e aprendizado pratico de agentes.

## Overview

Ubuntu AI Agent translates natural-language requests into controlled Linux actions. It combines local LLM reasoning with safety checks, operational memory and native system integrations so routine desktop and administration tasks can be executed with more context.

## Stack

- Python 3.12+
- Ollama/local LLM runtime
- SQLite operational memory
- CustomTkinter desktop UI
- Linux, D-Bus and system tooling

## Architecture

- Intent interpretation routes user requests into tool-oriented actions.
- Safety validation blocks dangerous commands before execution.
- Operational memory stores recent actions and useful environment facts.
- Native Linux integrations are preferred before falling back to shell commands.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

## Usage

Run the app locally, keep the configured LLM provider available, and request Ubuntu tasks in natural language. Review generated actions before allowing sensitive operations.

## Project Status

`active` / `portfolio`

This is a primary portfolio project for local AI agents, Linux automation and safety-oriented tooling.

## Roadmap

- Expand automated tests around safety validation.
- Document supported task categories.
- Add screenshots or a short demo recording.
