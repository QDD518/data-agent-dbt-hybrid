"""SQL security validator — unit tests (no external deps)."""

import pytest
from backend.sql.security import validate_sql, SQLSecurityError


class TestAllowedQueries:
    def test_simple_select(self):
        validate_sql("SELECT * FROM orders")

    def test_select_with_columns(self):
        validate_sql("SELECT id, name FROM customers")

    def test_select_with_join(self):
        validate_sql("SELECT a.*, b.name FROM orders a JOIN customers b ON a.customer_id = b.id")

    def test_select_with_subquery(self):
        validate_sql("SELECT * FROM (SELECT * FROM orders) t")

    def test_select_with_cte(self):
        validate_sql("WITH cte AS (SELECT * FROM orders) SELECT * FROM cte")

    def test_select_with_window(self):
        validate_sql("SELECT id, ROW_NUMBER() OVER (PARTITION BY status ORDER BY date) FROM orders")

    def test_select_with_group_by(self):
        validate_sql("SELECT status, COUNT(*) FROM orders GROUP BY status")

    def test_select_with_order_limit(self):
        validate_sql("SELECT * FROM orders ORDER BY id DESC LIMIT 10")


class TestBlockedQueries:
    def test_insert_blocked(self):
        with pytest.raises(SQLSecurityError, match="INSERT"):
            validate_sql("INSERT INTO orders VALUES (1)")

    def test_update_blocked(self):
        with pytest.raises(SQLSecurityError, match="UPDATE"):
            validate_sql("UPDATE orders SET status = 'done'")

    def test_delete_blocked(self):
        with pytest.raises(SQLSecurityError, match="DELETE"):
            validate_sql("DELETE FROM orders WHERE id = 1")

    def test_drop_blocked(self):
        with pytest.raises(SQLSecurityError, match="DROP"):
            validate_sql("DROP TABLE orders")

    def test_alter_blocked(self):
        with pytest.raises(SQLSecurityError, match="ALTER"):
            validate_sql("ALTER TABLE orders ADD COLUMN x INT")

    def test_create_blocked(self):
        with pytest.raises(SQLSecurityError, match="CREATE"):
            validate_sql("CREATE TABLE x (id INT)")

    def test_truncate_blocked(self):
        with pytest.raises(SQLSecurityError, match="TRUNCATE"):
            validate_sql("TRUNCATE TABLE orders")

    def test_grant_blocked(self):
        with pytest.raises(SQLSecurityError, match="GRANT"):
            validate_sql("GRANT SELECT ON orders TO user1")

    def test_exec_blocked(self):
        with pytest.raises(SQLSecurityError, match="EXEC"):
            validate_sql("EXECUTE some_function()")


class TestEdgeCases:
    def test_empty_string(self):
        with pytest.raises(SQLSecurityError, match="Empty"):
            validate_sql("")

    def test_whitespace_only(self):
        with pytest.raises(SQLSecurityError, match="Empty"):
            validate_sql("   ")

    def test_multiple_statements_blocked(self):
        with pytest.raises(SQLSecurityError, match="Multiple"):
            validate_sql("SELECT * FROM orders; SELECT * FROM customers")

    def test_single_statement_with_semicolon_allowed(self):
        validate_sql("SELECT * FROM orders;")

    def test_case_insensitive_keyword_detection(self):
        with pytest.raises(SQLSecurityError, match="INSERT"):
            validate_sql("insert into orders values (1)")

    def test_mixed_case_keyword(self):
        with pytest.raises(SQLSecurityError, match="DELETE"):
            validate_sql("Delete FROM orders")
