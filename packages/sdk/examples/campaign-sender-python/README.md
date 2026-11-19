# Campaign sender (Python, standard library only)

Sends one finished campaign email to a recipient list so that every click can
be tied to the person it was sent to. Aether never sends email itself
(ADR-C1); this tool runs on your side and uses your own SMTP server.

For each batch of up to 500 recipients it:

1. calls Aether `POST /v1/comms/click-tokens/tag-links`, which returns one copy
   per recipient with a signed `ae` token on every link to your own domains
   (`--allowed-host`). Links to other sites are left alone;
2. skips recipients Aether reports as `suppressed` (unsubscribe, complaint,
   provider suppression — the check fails closed) and invalid addresses;
3. sends each copy over SMTP with a `List-Unsubscribe` header when
   `--unsubscribe-url` is given;
4. writes each delivered message id to a local ledger right away, so rerunning
   the same `--send-id` never mails anyone twice;
5. reports `email_sent` (or `email_dropped` when your server refuses a
   recipient) to `POST /v1/comms/webhook`, identified by the tenant-scoped alias
   Aether returned — never the address. Reports that cannot be delivered are
   kept in `<ledger>.pending.jsonl` and retried on the next run; the run exits
   non-zero while any remain.

## Run

```bash
export AETHER_API_URL=https://api.example.com
export AETHER_API_KEY=...            # tenant API key with write permission
export AETHER_WEBHOOK_SECRET=...     # only if the tenant has a webhook signing secret
export SMTP_HOST=smtp.example.com SMTP_PORT=587 SMTP_USERNAME=... SMTP_PASSWORD=...
export MAIL_FROM="Shop <news@shop.test>"
```

```bash
python aether_campaign_sender.py \
  --send-id campaign-65-wave-1 --campaign-id campaign-65 \
  --subject "Our sale" --html message.html --text message.txt \
  --recipients recipients.csv --allowed-host shop.test \
  --unsubscribe-url https://shop.test/unsubscribe
```

`recipients.csv` needs a header row with an `email` column. `SMTP_SSL=true`
uses implicit TLS (port 465); `SMTP_STARTTLS=false` disables STARTTLS.

Preview first — this writes `.eml` files and sends and reports nothing:

```bash
python aether_campaign_sender.py ... --preview-dir ./preview
```

The run prints a JSON summary (`sent`, `suppressed`, `invalid`, `duplicate`,
`refused`, reports delivered and pending) with no email addresses.

## Requirements on your site

The tagged links only attribute clicks on pages that run the Aether web SDK
(or app deep links handled by the iOS/Android SDKs). The visitor's consent must
allow identity stitching for the click to be tied to the recipient.
