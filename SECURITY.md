# Security

Package recipes execute code during an explicitly requested build or install.
Review new recipes, use isolated build environments, and verify both the pinned
repository manifest and each archive before use. Checksums establish byte identity;
they do not establish the publisher's trustworthiness.

Do not put credentials, private source URLs, user data, or restricted payloads in
the repository or a public release. Never post secrets in a public issue. Use
GitHub's private vulnerability reporting interface when enabled; otherwise contact
the repository owner through an appropriate private channel.

Report archive traversal, integrity verification, installer, or execution-isolation
issues to the Compiler Playground project. Repository publication issues belong here.
