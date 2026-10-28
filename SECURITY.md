# Security policy

## Supported versions

The latest `0.1.x` source release receives security fixes. Older versions are
not maintained.

## Reporting a vulnerability

Do not post tokens, private repository data, email addresses or exploit details
in a public issue. Open a minimal issue asking for a private channel, or use the
repository's **Security → Report a vulnerability** form when private
vulnerability reporting is enabled.

## Security model

- GitHub credentials are read from the environment variable named by
  `github.token_env`. They are never accepted from YAML, written to events,
  reports or logs, or sent anywhere except the configured GitHub API.
- Use a fine-grained **read-only** GitHub token. The poller is designed to make
  read requests only and enforces a zero-write guard.
- Webhook delivery requires HTTPS. Plain HTTP is accepted only for exact
  loopback hosts (`localhost`, `127.0.0.1`, `::1`) for local testing; it must
  never carry a production credential or private payload to another host.
- SMTP credentials are read from the environment variables named in the config;
  STARTTLS is the default. Email is only as private as the configured mail
  provider.
- Configuration, event store, delivery logs and generated reports are local
  files. Protect them with normal OS account permissions.
- The tool is not a real-time GitHub integration and does not scrape. Keep
  polling within GitHub's terms and your token scopes.

## Limitations

No SLA is promised for this MIT-licensed, best-effort project. Security depends
on a least-privilege token, a trusted webhook/SMTP destination, and an
appropriately protected local account.
