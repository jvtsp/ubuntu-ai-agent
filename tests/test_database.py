"""
Testes para o módulo de persistência (storage/database.py).
"""


class TestDatabase:
    def test_init_creates_table(self, db_in_memory):
        """Tabela commands deve ser criada na inicialização."""
        with db_in_memory._connect() as conn:
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='commands'")
            assert cursor.fetchone() is not None

    def test_save_and_retrieve(self, db_in_memory):
        """Deve salvar e recuperar um comando."""
        db_in_memory.save_command(
            user_input="instale o vim",
            llm_response="```bash\nsudo apt install -y vim\n```",
            extracted_command="sudo apt install -y vim",
            stdout="Reading package lists...",
            stderr="",
            exit_code=0,
            confirmed=True,
        )
        history = db_in_memory.get_last_n(1)
        assert len(history) == 1
        assert history[0]["user_input"] == "instale o vim"
        assert history[0]["extracted_command"] == "sudo apt install -y vim"
        assert history[0]["exit_code"] == 0

    def test_save_returns_id(self, db_in_memory):
        """save_command deve retornar o ID do registro."""
        row_id = db_in_memory.save_command(user_input="teste")
        assert isinstance(row_id, int)
        assert row_id > 0

    def test_get_last_n_order(self, db_in_memory):
        """get_last_n deve retornar em ordem cronológica (antigo primeiro)."""
        db_in_memory.save_command(user_input="primeiro")
        db_in_memory.save_command(user_input="segundo")
        db_in_memory.save_command(user_input="terceiro")
        history = db_in_memory.get_last_n(3)
        assert history[0]["user_input"] == "primeiro"
        assert history[2]["user_input"] == "terceiro"

    def test_get_last_n_limits(self, db_in_memory):
        """get_last_n deve respeitar o limite N."""
        for i in range(10):
            db_in_memory.save_command(user_input=f"cmd_{i}")
        history = db_in_memory.get_last_n(3)
        assert len(history) == 3

    def test_get_last_n_empty(self, db_in_memory):
        """get_last_n deve retornar lista vazia se não há registros."""
        history = db_in_memory.get_last_n(5)
        assert history == []

    def test_clear_history(self, db_in_memory):
        """clear_history deve remover todos os registros."""
        db_in_memory.save_command(user_input="cmd1")
        db_in_memory.save_command(user_input="cmd2")
        removed = db_in_memory.clear_history()
        assert removed == 2
        assert db_in_memory.get_last_n(10) == []

    def test_clear_empty_history(self, db_in_memory):
        """clear_history em banco vazio deve retornar 0."""
        assert db_in_memory.clear_history() == 0

    def test_save_with_none_fields(self, db_in_memory):
        """Deve aceitar campos opcionais como None."""
        row_id = db_in_memory.save_command(
            user_input="test",
            llm_response=None,
            extracted_command=None,
            stdout=None,
            stderr=None,
            exit_code=None,
            confirmed=False,
        )
        assert row_id > 0

    def test_save_unicode(self, db_in_memory):
        """Deve lidar com caracteres unicode (pt-BR, emojis)."""
        db_in_memory.save_command(
            user_input="crie arquivo na Área de Trabalho 🐧",
            extracted_command='touch "$DESKTOP/teste.txt"',
        )
        history = db_in_memory.get_last_n(1)
        assert "Área de Trabalho" in history[0]["user_input"]
        assert "🐧" in history[0]["user_input"]
