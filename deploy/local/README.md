# Server-only Caddy additions

Files `*.caddy` in this folder are read by Caddy on the VPS (`import` in `deploy/Caddyfile`,
mounted by `docker-compose.prod.yml`). They are git-ignored, so the automatic update (`git pull`)
never stops on them. Put here anything that only this server has, instead of editing `deploy/Caddyfile`.

Example `deploy/local/extra.caddy`:

```
handle /my-page* {
	respond "Hello"
}
```

After adding or changing a file: `docker compose restart caddy`.
Never put passwords or keys in the repository; files here stay only on the server.
