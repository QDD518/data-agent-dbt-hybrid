-- ChatBI Demo: E-commerce Database Initialization
-- This runs automatically on first PostgreSQL container start

CREATE SCHEMA IF NOT EXISTS analytics;

-- Note: Tables are created by dbt via `dbt run`, not here.
-- This file only creates the schema so the dbt profile can connect.
-- Seed data lives in dbt_project/seeds/*.csv and is loaded via `dbt seed`.
