-- Create additional databases needed by services
CREATE DATABASE langfuse;

-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;
