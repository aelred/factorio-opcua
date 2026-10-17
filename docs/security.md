# Security

The bridge is an OPC UA server that can change your factory, so decide who
may reach it and what they may do. Everything here is set in the `[opcua]`
section of the config file (see `bridge/example.toml`).

## Defaults

| Setting | Default | Meaning |
|---|---|---|
| `endpoint` | `opc.tcp://127.0.0.1:4840/factorio-opc/` | Only this machine can connect |
| `security` | `["none", "sign_encrypt"]` | Offer unencrypted and encrypted endpoints |
| `anonymous` | `"write"` | Clients without a login may read and write |
| `users` | none | |

That's convenient for local testing. To listen on the network, change the
endpoint host to `0.0.0.0` or a specific address. In that case the bridge
**refuses to start** while unencrypted anonymous access is still allowed.
Fix that with one of:
- `anonymous = "none"`, plus users (recommended),
- `security = ["sign_encrypt"]` (encrypted only), or
- `allow_insecure = true` (accept the risk; the bridge logs a warning).

## Security modes

`security` lists the endpoint modes to offer:

| Mode | Endpoints offered |
|---|---|
| `none` | No signing or encryption |
| `sign` | Basic256Sha256 and Aes256_Sha256_RsaPss, signed |
| `sign_encrypt` | Basic256Sha256 and Aes256_Sha256_RsaPss, signed and encrypted |

**Server certificate:** any mode other than `none` needs one. By default,
the bridge creates a self-signed certificate in `pki_dir`
(`~/.factorio-opc/pki`):
- **Files:** `server_cert.der` and `server_key.pem`; the key file is
  readable only by you.
- **Names:** it covers this machine's host name, `localhost`, 127.0.0.1 and
  the endpoint's address.
- **Renewal:** it's replaced when it nears expiry (one year), or when the
  endpoint changes to an address it doesn't cover. The key is kept.

To use your own certificate instead, set `certificate` (DER or PEM) and
`private_key` (PEM).

Clients must trust the server certificate the first time they connect; most
clients ask.

**Client certificates:** the bridge accepts any client certificate. It uses
them only to encrypt the connection, not to decide who the client is. Use
`users` for that.

## Users and roles

```toml
[opcua]
anonymous = "none"         # none, read or write

[[opcua.users]]
name = "operator"
password_hash = "scrypt$16384$8$1$..."   # factorio-opc hash-password
role = "write"

[[opcua.users]]
name = "dashboard"
password_hash = "scrypt$..."
role = "read"              # the default
```

- **Read** users (and `anonymous = "read"`) can browse, read and subscribe.
  Writing a value or calling a method returns `BadUserAccessDenied`.
- **Write** users can also write writer signals and call `SetSignals` and
  `ClearAll`.
- **Anonymous:** `anonymous = "none"` refuses clients that don't log in.
- **Unknown or wrong logins** are refused, including a user called "admin".
  No client can ever change the address space.
- **Password hashes:** `factorio-opc hash-password` asks for a password and
  prints the hash for `password_hash`. A plain `password = "..."` is also
  accepted, but it puts the password in the config file.
- **Password transport:** passwords are sent encrypted whenever the bridge
  has a certificate, which it does when `security` includes `sign` or
  `sign_encrypt`, even if the client uses the `none` endpoint. Without a
  certificate they travel in plain text.

## Audit log

Every write, whether to a value or through a method, is logged at INFO,
with who made it and whether the game accepted it:

```
2026-10-17 20:30:01 INFO factorio_opc: write press {"item/iron-plate": 5} by operator
```

With `--log-format json` (or `log_format = "json"` under `[bridge]`), each
line is a JSON object with the fields `tag`, `signals`, `mode`, `via`
(`write` or `method`), `user` and `result` (`ok`, `rejected`, `failed` or
`offline`). That's ready for a log collector.

## RCON

RCON between the bridge and Factorio is **not encrypted**, and its password
gives full control of the server. Run the bridge on the same machine as the
server, or on a private network, and don't expose the RCON port.

## Connecting with opcua-client (encrypted, with a login)

These steps are for opcua-client **1.0.2 or newer**, which needs Python
3.14 (`uv tool install --python 3.14 opcua-client`).

1. Enter `opc.tcp://127.0.0.1:4840/factorio-opc/` and press **Connect**.
2. In the **Connect to server** dialog, choose **SignAndEncrypt** and pick an
   endpoint. Basic256Sha256 and Aes256_Sha256_RsaPss both work.
3. Choose **Username**, then enter the user and password.
4. Press **Connect**. On the first encrypted connection, opcua-client creates
   its own client certificate. The bridge needs no copy of it.

Checked with opcua-client 1.0.2 under Python 3.14: an Aes256_Sha256_RsaPss +
SignAndEncrypt connection, logged in as a write user, read values and set
two signals in one `SetSignals` call.

**Older opcua-client (0.8.4).** pip installs 0.8.4 on Python 3.13 and older.
It can't create a certificate, and its Settings → Client Application
Certificate dialog crashes (`NameError: name 'QDialog' is not defined`).
To work around both:
- Make a certificate with `factorio-opc make-client-cert ~/uaclient-cert`.
- Register it with `python3 scripts/opcua-client-set-cert.py ~/uaclient-cert`,
  run with opcua-client closed.
- Put the login in the address: `opc.tcp://user:pass@...`.
- Under **Connect options → Query server capability**, choose Basic256Sha256.

Upgrading is easier.
