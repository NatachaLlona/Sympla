# Project conventions

- All application messages, prompts, API documentation and code comments are in English.
- Always distinguish API accounts, database accounts, operating-system accounts and application accounts.
- Use qualified identifiers such as `api_account`, `api_user_identifier`, `client_id` and `database_account_name`.
- Do not introduce generic account identifiers or ambiguous account labels.
- Preserve external framework/driver protocol keys and historical migration/database column identifiers needed for compatibility. Map them to qualified application identifiers rather than rewriting applied history.
- Swagger Authorize is the only interactive API authentication form. Never send an HTTP Basic authentication challenge that opens a browser-native sign-in dialog.
- Preserve configured API client IDs and chosen client secrets during upgrades. Never reset credentials as a troubleshooting shortcut.
