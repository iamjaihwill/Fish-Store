# Reef & Rift — saltwater aquarium storefront + CMS

A complete saltwater livestock store: a public storefront for corals, fish, inverts and
dry goods, plus a content-managed admin that shop staff run the whole site from — catalog,
homepage composition, policy pages, live sale calendar and order fulfillment.

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
  loser gets a clear message and an adjusted cart rather than an oversold order.

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

Rich text fields accept either plain text (blank lines become paragraphs, everything is
escaped) or authored HTML — copy that *begins* with a block-level tag is passed through as
markup. Checking only the opening token means prose like `keep alkalinity < 9 dKH` is
escaped correctly instead of being mistaken for HTML.

## Layout

```
config/            settings, root URLconf, WSGI
apps/
  core/            shared utilities, seed command, procedural image generator
  catalog/         Category, Product, ProductImage, Collection, Tag + browsing views
  cms/             SiteSettings, HeroSlide, HomepageSection, Page, FAQ, nav, events
  shop/            Cart, Order, OrderItem, DoaClaim, checkout services
templates/         storefront templates (base, partials, per-app)
static/css/        one hand-written stylesheet
static/js/         progressive enhancement only — every feature works without it
```

## Tests

```
.venv/bin/python manage.py test
```

103 tests covering catalog filtering and publication rules, WYSIWYG quantity enforcement,
cart arithmetic and stock clamping, shipping and tax quoting, the checkout race condition,
order privacy, CMS rendering and validation, the admin bulk actions, and the seed command.

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

**Payment is deliberately not wired up.** Orders are created with status *Awaiting payment*
and the customer is told they will be invoiced; this matches how many coral shops actually
operate (especially for live sale claims). Dropping in Stripe means adding a payment step
between `place_order` and the confirmation redirect in `apps/shop/views.py` — the order,
totals and inventory hold are already in place at that point.

SQLite is fine for a store this size. If you outgrow it, `DATABASES` is the only thing that
needs to change.
