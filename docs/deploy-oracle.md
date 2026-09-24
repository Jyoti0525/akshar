# Deploying the AKSHAR API on Oracle Cloud (Always Free)

The web app is already on Vercel. This guide puts the **API with real scanning** on
an Oracle Cloud virtual machine and points Vercel at it.

Why Oracle is the right place for it:

| | memory | what happens to a scan |
|---|---|---|
| Render free | 512 MB | the models cannot load, so scanning runs in a degraded tier |
| Oracle Always Free (Ampere A1) | **up to 24 GB** | a scan peaks around 1.2–1.8 GB, so it runs in full, with room to spare |

It is also a real machine that does not go to sleep, so there is no cold
one-minute wait on the first click like Render has.

**Three things to know before you start:**

1. **Oracle asks for a card to verify you.** It is not charged on the free tier.
   Our earlier signup attempt did not complete; if the card is refused again, a
   different card (a credit card rather than a debit or prepaid one) usually works.
2. **Your home region is permanent.** Choose **India West (Mumbai)** or **India
   South (Hyderabad)** at signup. It cannot be changed later.
3. **"Out of capacity" is common** when you create the machine. It is not an
   error on your side. The fixes are in step 2.

---

## What goes where

```
browser ──► Vercel (web app) ──► https://api.<your-ip>.sslip.io ──► Neon (database)
                                  │
                                  └─ Oracle VM: Caddy (HTTPS) ──► AKSHAR API in Docker
```

**The 1.8 GB is not something you upload.** It is the Docker image, which is
mostly Python libraries, and it gets **built on the Oracle machine** from the
GitHub code. The only thing you copy from your laptop is `data/models`, about
170 MB, because the model weights are not in git.

Building on Oracle also means your laptop does not have to run the Docker build,
which is the step that ran it out of memory before.

---

## 1. Sign up

1. Go to <https://signup.cloud.oracle.com>.
2. Account type: **Individual**.
3. Home region: **India West (Mumbai)**.
4. Complete the card verification.
5. Wait for the "your account is ready" email. It can take anywhere from a few
   minutes to an hour. Sign in at <https://cloud.oracle.com> once it arrives.

## 2. Create the virtual machine

Menu (☰) → **Compute** → **Instances** → **Create instance**.

| Setting | Choose |
|---|---|
| Name | `akshar-api` |
| Image | **Change image** → **Canonical Ubuntu** → **22.04** (the plain one, not "Minimal") |
| Shape | **Change shape** → **Ampere** → `VM.Standard.A1.Flex` → **2 OCPUs, 12 GB memory** |
| Networking | **Create new virtual cloud network**, **Create new public subnet**, **Assign a public IPv4 address: Yes** |
| SSH keys | **Generate a key pair for me** → **Save private key** and **Save public key** |
| Boot volume | leave the default |

Click **Create**.

**Keep the private key file safe.** It is the only way into the machine. Move it
somewhere permanent, for example `C:\Users\jyoti\.ssh\akshar-oracle.key`.

**Why 2 OCPUs and 12 GB, not the full 4 and 24:** it is still six times what a
scan needs, it leaves half your free allowance spare, and a smaller request is
much more likely to get past "Out of capacity".

**If you see "Out of capacity for shape VM.Standard.A1.Flex":**

- Under **Placement**, change the **availability domain** and try again (if your
  region has more than one).
- Try 1 OCPU / 6 GB. That is still enough for scanning.
- Try again after a few hours. Capacity comes and goes, and early morning India
  time tends to be easier.

When the instance shows **Running**, copy its **Public IP address** from the
instance page. The rest of this guide calls it `YOUR_IP`.

## 3. Open ports 80 and 443 in Oracle's firewall

Oracle blocks all web traffic by default. On the instance page:

1. Click the **subnet** link (under Primary VNIC).
2. Click the **Default Security List**.
3. **Add Ingress Rules**, twice:

| Source CIDR | IP Protocol | Destination Port |
|---|---|---|
| `0.0.0.0/0` | TCP | `80` |
| `0.0.0.0/0` | TCP | `443` |

Port 80 is only there so the HTTPS certificate can be issued. Do **not** open
port 8000. The API should only be reachable through HTTPS.

## 4. Connect to the machine

In **PowerShell** on your laptop:

```powershell
# Windows refuses to use a key that other accounts can read. Fix it once:
icacls C:\Users\jyoti\.ssh\akshar-oracle.key /inheritance:r /grant:r "$($env:USERNAME):R"

ssh -i C:\Users\jyoti\.ssh\akshar-oracle.key ubuntu@YOUR_IP
```

Type `yes` the first time. You are now on the Oracle machine. Every command from
here to step 11 runs **there**, unless it says otherwise.

## 5. Open the same ports inside Ubuntu

Oracle's Ubuntu images come with their **own** firewall on top of the one from
step 3. If you skip this, everything looks right and the site still does not
load.

```bash
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save
```

## 6. Install Docker

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker ubuntu
exit
```

`exit` disconnects you. Reconnect with the same `ssh` command from step 4, so
the new permission takes effect. Then check it:

```bash
docker run --rm hello-world
```

## 7. Get the code onto the machine

```bash
git clone https://github.com/Jyoti0525/akshar.git
cd akshar
```

If the repository is private, GitHub will ask for a password. Use a **personal
access token** instead (GitHub → Settings → Developer settings → Personal access
tokens → Fine-grained → read-only access to this repository).

## 8. Copy the model weights from your laptop

Open a **second PowerShell window on your laptop** (leave the SSH one open), go
to the project folder, and run:

```powershell
cd C:\Users\jyoti\codefiles\SIH_26034
scp -i C:\Users\jyoti\.ssh\akshar-oracle.key -r data\models ubuntu@YOUR_IP:~/akshar/data/
```

About 170 MB. Back in the SSH window, check it arrived:

```bash
ls ~/akshar/data/models
```

You should see **15 files**: the BGE retrieval model and its tokenizer, the
three OCR recognisers with their `.yml` files, three dictionary `.txt` files,
the text detector, the field classifier, the SKU embedder and `sku_pca_512.npz`.

## 9. Build the image

```bash
cd ~/akshar
docker build -f docker/api.Dockerfile -t akshar-api .
```

This takes around 10 to 20 minutes the first time. The last step deliberately
fails the build if PDF rendering is broken, so a successful build means reports
work.

**This machine is ARM, not the Intel/AMD your laptop uses.** Every library the
API depends on publishes ARM builds, so this should go through unchanged, but it
has not been built on ARM before. If `pip` fails on a particular package, copy
the last 30 lines of the output and send them over.

Check the models made it into the image:

```bash
docker run --rm akshar-api ls data/models
```

Same 15 files as step 8. If that list is empty, stop here, because the deployed
API would run without being able to read labels.

## 10. Write the settings file

First make a signing secret:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

Then create the file:

```bash
nano ~/akshar.env
```

Paste this, filling in the three values:

```
AKSHAR_ENVIRONMENT=production
AKSHAR_STORAGE=sql
AKSHAR_JWT_SECRET=PASTE_THE_SECRET_FROM_ABOVE
AKSHAR_DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST/neondb?sslmode=require
AKSHAR_CORS_ORIGINS=https://YOUR-APP.vercel.app
AKSHAR_MINIO_ENDPOINT=
```

Save with `Ctrl+O`, `Enter`, then `Ctrl+X`. Lock it so only you can read it:

```bash
chmod 600 ~/akshar.env
```

Things that will bite you if they are wrong:

- **No quotes** around any value in this file. Docker keeps them as part of the
  value.
- **The database URL must start with `postgresql+psycopg://`**, not
  `postgresql://`. Without it the API cannot load the database driver.
- **Rotate the Neon password first**, because the old one was pasted into a chat.
  Use the new one here, and update it on Render too if Render is still running.
- `AKSHAR_CORS_ORIGINS` is your Vercel URL with `https://` and **no** slash at the
  end.
- **Keep `AKSHAR_MINIO_ENDPOINT=` with nothing after the `=`.** It says there is
  no evidence-photo storage on this host. Leave the line out and the API
  refuses to start in production: it sees the local MinIO address it defaults
  to, finds that storage's development password, and stops. The container then
  restarts over and over, and `curl` reports `Connection reset by peer`.

## 11. Start the API

```bash
docker run -d \
  --name akshar-api \
  --restart unless-stopped \
  --env-file ~/akshar.env \
  -p 127.0.0.1:8000:8000 \
  akshar-api
```

- `--restart unless-stopped` brings it back after a crash or a machine reboot.
- `127.0.0.1:8000` means the API only listens inside the machine. The outside
  world reaches it through Caddy in step 12, over HTTPS.

Give it 20 seconds, then:

```bash
curl http://127.0.0.1:8000/healthz
```

Look for `"models_present": 11, "models_expected": 12`. **Eleven is correct.**
The package detector (RTMDet) is not trained yet, and the scan falls back to a
simpler package outline without it. `0 present` means step 8 or 9 went wrong.

If `curl` just hangs, the database URL is wrong or Neon is unreachable. See the
logs:

```bash
docker logs akshar-api --tail 50
```

## 12. HTTPS with Caddy

Vercel should talk to the API over HTTPS, not plain HTTP. Caddy gets a free
certificate automatically.

**You do not need to buy a domain.** `sslip.io` turns any IP address into a
hostname: `api.129-154-10-20.sslip.io` points at `129.154.10.20`. Write your IP
with **dashes instead of dots**.

Install Caddy:

```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update
sudo apt install -y caddy
```

Configure it:

```bash
sudo nano /etc/caddy/Caddyfile
```

Delete everything in the file and replace it with (your IP, with dashes):

```
api.129-154-10-20.sslip.io {
    reverse_proxy 127.0.0.1:8000
}
```

Save, then:

```bash
sudo systemctl reload caddy
```

Now, **from your laptop**, open this in a browser:

```
https://api.129-154-10-20.sslip.io/healthz
```

You should see the same JSON as step 11, with a padlock in the address bar.

If the certificate fails (`journalctl -u caddy --no-pager | tail -30` on the
server shows why), the usual cause is step 3 or step 5 not being done, because
the certificate check comes in on port 80. If both are fine and it still fails,
get a free hostname from <https://www.duckdns.org>, point it at `YOUR_IP`, and use
that in the Caddyfile instead.

## 13. Make sure the database has tables and accounts

**If the Render deployment was already working with this same Neon database,
skip this step.** The tables and sign-in accounts are already there.

For a fresh Neon database, create the tables. Note that `psql` wants the URL
**without** `+psycopg`:

```bash
cd ~/akshar
docker run --rm -i postgres:16 psql "postgresql://USER:PASSWORD@HOST/neondb?sslmode=require" < db/schema.sql
```

Then create the three demo sign-ins:

```bash
docker exec akshar-api python -c "
from api.sql.engine import get_engine
from api.sql.stores import SqlUserStore
from api.demo import seed_accounts
print([u.email for u in seed_accounts(SqlUserStore(get_engine()))])
"
```

That prints `officer@akshar.demo`, `supervisor@akshar.demo` and
`admin@akshar.demo`. The password for all three is `akshar-demo`.

## 14. Point Vercel at it

Vercel → your project → **Settings** → **Environment Variables**:

| Name | Value |
|---|---|
| `AKSHAR_API_ORIGIN` | `https://api.129-154-10-20.sslip.io` |

`https://` included, no slash at the end.

**Then redeploy.** Vercel only applies a changed variable to a new deployment:
**Deployments** → the latest one → **⋯** → **Redeploy**.

## 15. Test the whole thing

1. Open your Vercel URL.
2. Sign in as `officer@akshar.demo` / `akshar-demo`.
3. Upload a label photograph, enter the pack height, run the scan.
4. The result should show text read from the label. That is the part that did
   **not** work on Render.
5. Export the PDF report.

If anything fails, run `docker logs akshar-api --tail 50` on the server first.
That shows the actual error.

---

## Day-to-day

**Updating after a code change** (on the server):

```bash
cd ~/akshar
git pull
docker build -f docker/api.Dockerfile -t akshar-api .
docker rm -f akshar-api
docker run -d --name akshar-api --restart unless-stopped --env-file ~/akshar.env -p 127.0.0.1:8000:8000 akshar-api
```

Vercel redeploys the web app by itself on every push to `main`.

**If you change the models**, copy them again with the `scp` from step 8 before
you rebuild.

**Render.** Once step 15 works, the Render API is not needed. Keep it as a backup
or delete it. Vercel only talks to whichever address is in `AKSHAR_API_ORIGIN`.

**Idle machines.** Oracle may stop an Always Free machine that has been nearly
idle for 7 days in a row, and emails you first. If that happens, start it again
from the Instances page; the container and Caddy come back up on their own.
Upgrading the account to **Pay As You Go** removes this rule, and Always Free
resources still cost nothing on it.
