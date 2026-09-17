# Reef & Rift — saltwater aquarium storefront + CMS

A complete saltwater livestock store: a public storefront for corals, fish, inverts and
dry goods, plus a content-managed admin that shop staff run the whole site from — catalog,
homepage composition, policy pages, live sale calendar, rewards and order fulfillment.

Built with Django 5 and SQLite. No JavaScript build step, no framework CSS, no paid
services required to run it.

```
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python manage.py migrate
.venv/bin/python manage.py seed_store --admin-password=changeme
.venv/bin/python manage.py runserver
```

Storefront at http://127.0.0.1:8000/ · CMS at http://127.0.0.1:8000/admin/ (`admin` / the
password you passed above).

---

## What the storefront does

**Browsing.** A filterable shop grid (care level, lighting, flow, price, type, WYSIWYG,
on-sale, aquacultured, in-stock) with sorting and pagination, category pages that include
their sub-categories, curated collection pages, and full-text search across name,
scientific name and description.

**Product pages.** Image gallery with thumbnails, a care requirements table that renders
only the fields actually filled in, acclimation notes, live arrival and shipping
accordions, tags, and related items.

**Cart and checkout.** Session cart that re-reads price and stock from the catalog on
every render, so a stale cart can never check out at yesterday's price or claim a coral
that has since sold. Checkout collects the address, a requested ship date and a weather-hold
preference, and requires accepting the livestock terms when the cart contains animals.

**After the sale.** Order lookup by number + email, a delivery status track, and a
dead-on-arrival claim form that opens for eight hours after delivery is recorded.

**Accounts.** Registration claims past guest orders on the same email, so history is never
stranded by having checked out as a guest. Saved addresses prefill checkout, a wishlist
doubles as the back-in-stock notification list, and order history spans both account and
guest purchases.

**Reviews.** Moderated before publishing, with a verified-purchase badge driven by whether
that email or account actually bought the item on a non-cancelled order.

**Money.** Reward points, gift cards and discount codes, all priced through one function so
they stack in a fixed order. Payments run through a pluggable backend: invoice by default,
Stripe when configured.

**Content.** Care guides and species spotlights, sitemap.xml, robots.txt, Product JSON-LD
with price, availability and aggregate rating, Open Graph tags, and instant search
suggestions in the header.

## Livestock-specific behaviour

This is the part that separates a coral store from ordinary retail, and it is modelled
rather than bolted on:

- **WYSIWYG listings** — a single physical animal. Setting the flag forces inventory
  tracking on and caps quantity at one, everywhere: model, cart, and checkout.
- **Overnight shipping** is forced on for anything in a livestock category, and shipping
  is quoted at the livestock rate whenever a cart contains any animal.
- **Requested ship date and weather holds** are captured at checkout, because the customer
  has to be home to receive the box.
- **The DOA window** opens when staff mark an order delivered and closes eight hours later.
- **Stock is locked at checkout.** Order placement runs in a transaction with
  `select_for_update`, so two people racing for the last colony cannot both win it — the
  loser gets a clear message and an adjusted cart rather than an oversold order. This
  matches how these stores describe their own live sales: the same coral can sit in
  several carts, and the first to finish checkout takes it.
- **Add to an existing order.** A customer who wins several corals across a live sale
  evening puts each later win into a box that has not shipped yet, instead of paying
  overnight shipping twice.
- **A shipping calendar, not just shipping days.** Orders before a configurable cutoff go
  out the same business day; after it, the next ship day. A requested delivery date that
  is not a ship day is rejected with the next available day named.
- **Variants where livestock needs them** — frag vs. mini colony, pack sizes — with the
  variant owning price and stock, and the listing showing a "from" price.
- **Frag packs and mystery boxes**, where a pack lists its contents and a mystery box
  deliberately does not.
- **Wholesale pricing** for approved trade accounts. Applying is not approval.
- **Points cannot be spent during a live sale** but are still earned during one.

## What staff manage in the CMS

Everything below is editable in the admin without touching code or redeploying:

| Area | What it controls |
| --- | --- |
| **Site settings** | Store name, logo, announcement bar, contact details, social links, shipping rates, free-shipping threshold, tax rate, shipping days, guarantee wording |
| **Homepage sections** | The ordered bands on the homepage. Nine kinds: featured, new arrivals, WYSIWYG picks, on sale, a specific collection, category grid, rich text, trust bar, testimonials |
| **Hero slides** | Headline, image, two CTAs, with optional start/end scheduling |
| **Products** | Full catalog with reef care attributes, pricing, inventory, and bulk actions (publish, feature, mark sold out, relist a WYSIWYG piece) |
| **Categories / Collections / Tags** | Navigation structure and curated merchandising groups |
| **Pages** | Policy and guide pages (guarantee, shipping, acclimation, about) with SEO fields |
| **FAQ, Navigation links, Testimonials** | Support content and header/footer menus |
| **Live sale events** | Scheduled drops with countdown timers and a linked collection |
| **Orders** | Fulfillment workflow with bulk actions: paid → packing → shipped → delivered, cancel-and-restock, tracking numbers |
| **DOA claims, Contact messages, Subscribers** | Customer service inboxes |
| **Variants, videos, pack contents** | Per-product options, YouTube/Vimeo/MP4 video, frag pack contents |
| **Reviews** | Moderation queue with bulk publish/reject and staff replies |
| **Rewards settings, gift cards, discount codes** | Earn rate, expiry, redemption rules; card balances; promo codes and their redemptions |
| **Payments** | Charge records, off-site payment recording, provider refunds |
| **Customers** | Profiles, addresses, wholesale approval |
| **Care guides** | Blog articles with SEO fields and related products |

Rich text fields accept either plain text (blank lines become paragraphs, everything is
escaped) or authored HTML — copy that *begins* with a block-level tag is passed through as
markup. Checking only the opening token means prose like `keep alkalinity < 9 dKH` is
escaped correctly instead of being mistaken for HTML.

## Layout

```
config/            settings, root URLconf, WSGI
apps/
  core/            shared utilities, seed command, procedural image generator
  accounts/        Customer, Address, WishlistItem + the account area
  catalog/         Product, Variant, Image, Video, Bundle, Collection, Tag + browsing
  cms/             SiteSettings, homepage composition, Pages, FAQ, events, Articles, sitemaps
  shop/            Cart, Order, pricing, checkout, order additions, DOA claims
  reviews/         Moderated reviews with verified-purchase detection
  rewards/         Points ledger, gift cards, discount codes
  payments/        Backend contract, invoice/credit/Stripe backends, webhooks
templates/         storefront templates (base, partials, per-app)
static/css/        one hand-written stylesheet
static/js/         progressive enhancement only — every feature works without it
```

### Two design decisions worth knowing

**Variants are optional, not universal.** A product without variants sells on its own price
and stock. Once it has variants, the variant owns price and inventory. This keeps simple
listings simple, which is most of a coral catalog, at the cost of two code paths in the
cart — a trade made deliberately, and the reason the variant refactor landed without
rewriting a single existing test.

**Credits stack in a fixed order.** Discount code comes off the merchandise, tax is charged
on the discounted goods, then points, then gift cards — which behave like money and cover
shipping and tax as well as goods. All of it lives in `apps/shop/pricing.py`, so there is
exactly one place where an order total is decided.

## Tests

```
.venv/bin/python manage.py test
```

287 tests covering catalog filtering and publication rules, WYSIWYG quantity enforcement,
variant stock and cart separation, cart arithmetic and stock clamping, shipping and tax
quoting, the checkout race condition, order privacy, account registration and guest-order
claiming, wishlist and restock alerts, review moderation and verified purchases, points
expiry and redemption limits, gift card overdraw and splitting, the payment webhook path
including forged and replayed signatures, the shipping cutoff calendar, order additions,
wholesale pricing, CMS rendering, SEO output, the admin bulk actions, and the seed command.

## Seeding

`seed_store` fills an empty install with 25 products across 16 categories, plus pages, FAQ,
navigation, a live sale, testimonials and homepage composition. It is idempotent — running
it twice will not duplicate anything.

```
manage.py seed_store                        # seed, generating imagery
manage.py seed_store --no-images            # much faster, no placeholder photos
manage.py seed_store --flush                # wipe catalog and content first
manage.py seed_store --admin-password=...   # also create/refresh the 'admin' superuser
```

Product photography is generated procedurally with Pillow (a water gradient, a bloom of
polyp-like shapes, suspended particles, a soft-focus pass), so the demo looks like a real
store without committing binary assets. Replace the images with real photography via the
admin.

## Deployment notes

Set `DJANGO_DEBUG=False` and a real `DJANGO_SECRET_KEY`; see `.env.example` for the full
list. With `DEBUG=False` the app enables HSTS, secure cookies and SSL redirect, and serves
static files through WhiteNoise (`manage.py collectstatic` first). Media files are written
to `DJANGO_MEDIA_ROOT` — put that on persistent storage.

**Payments** default to the invoice backend, which needs no credentials and matches how many
coral shops actually operate, especially for live sale claims where the final box is
assembled from several wins. To take cards, set `DJANGO_PAYMENT_BACKEND=stripe` plus
`DJANGO_STRIPE_SECRET_KEY`, `DJANGO_STRIPE_PUBLISHABLE_KEY` and
`DJANGO_STRIPE_WEBHOOK_SECRET`, and point a Stripe webhook at `/payments/webhook/`. The
Stripe backend was written and tested against mocked API responses — it has never been run
against live Stripe credentials, so verify it in test mode before taking real money.

**Analytics** emit nothing unless `DJANGO_ANALYTICS_ID` is set. Plausible, Fathom and GA4
are supported.

**Scheduled work:** run `manage.py send_restock_alerts` on a timer (cron, systemd, Celery
beat) to email wishlist holders when sold-out products return.

SQLite is fine for a store this size. If you outgrow it, `DATABASES` is the only thing that
needs to change.
