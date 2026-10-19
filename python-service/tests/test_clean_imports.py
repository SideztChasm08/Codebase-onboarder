def test_clean_environment_runtime_imports():
    # Run after installing requirements.txt in a clean environment.
    import chunk_schema  # noqa: F401
    import embeddings  # noqa: F401
    import index_cli  # noqa: F401
    import indexing  # noqa: F401
    import initialize_db  # noqa: F401
    import vector_store  # noqa: F401
