"""Populate the store with a realistic demo catalog and site content."""

import random
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from apps.catalog.models import (
    BundleItem,
    CareLevel,
    Category,
    Collection,
    CollectionItem,
    FlowLevel,
    LightLevel,
    Placement,
    Product,
    ProductImage,
    ProductType,
    ReefSafe,
    ProductVariant,
    ProductVideo,
    Tag,
    Temperament,
)
from apps.rewards.models import DiscountCode, GiftCard, RewardsSettings
from apps.reviews.models import Review
from apps.cms.models import (
    Article,
    FaqItem,
    HeroSlide,
    HomepageSection,
    LiveSaleEvent,
    NavigationLink,
    Page,
    SiteSettings,
    Testimonial,
)
from apps.core.imagegen import generate_image

CATEGORIES = [
    ("Corals", ProductType.CORAL, "acan", "Aquacultured frags and show colonies, grown under our own lights.", [
        ("SPS", "acro"), ("LPS", "acan"), ("Soft corals", "torch"), ("Zoanthids", "zoa"),
    ]),
    ("Fish", ProductType.FISH, "fish", "Quarantined, eating and settled before they are ever listed.", [
        ("Tangs", "fish"), ("Clownfish", "fish"), ("Wrasses", "fish"),
    ]),
    ("Invertebrates", ProductType.INVERT, "invert", "Clean-up crews, shrimp and the oddballs that keep a reef honest.", [
        ("Clean-up crew", "invert"), ("Shrimp & crabs", "invert"),
    ]),
    ("Dry goods", ProductType.DRY_GOODS, "gear", "The gear we actually run on our own systems.", [
        ("Lighting", "gear"), ("Salt & additives", "gear"), ("Test kits", "gear"),
    ]),
]

CORALS = [
    ("Rift Fire Acan Lord", "Acanthastrea lordhowensis", "LPS", 189, 249, "acan",
     "beginner", "medium", "low", "bottom", True, True,
     "Five heavy polyps of orange and teal on a stable plug. Feeds aggressively on mysis."),
    ("Midnight Torch", "Euphyllia glabrescens", "LPS", 340, None, "torch",
     "intermediate", "medium", "medium", "middle", True, True,
     "Deep teal tentacles with violet tips. Three heads on the original mother plug."),
    ("Bioluminescent Hammer", "Euphyllia ancora", "LPS", 275, 320, "torch",
     "beginner", "medium", "medium", "middle", True, True,
     "Gold-tipped hammer that glows hard under blues. One of our steadiest growers."),
    ("Abyss Walker Acropora", "Acropora tenuis", "SPS", 145, None, "acro",
     "expert", "high", "high", "top", True, False,
     "Blue-based tenuis with contrasting polyps. Wants stable alkalinity and real flow."),
    ("Static Discharge Milli", "Acropora millepora", "SPS", 120, 160, "acro",
     "expert", "high", "high", "top", True, True,
     "Electric green milli that colours up fast once it is settled."),
    ("Tidal Rainbow Chalice", "Echinophyllia aspera", "LPS", 210, None, "chalice",
     "intermediate", "low", "low", "bottom", True, True,
     "Rainbow eyes across a cream base. Low light, low flow, patient feeder."),
    ("Nebula Zoa Garden", "Zoanthus sp.", "Zoanthids", 85, 110, "zoa",
     "beginner", "medium", "medium", "any", True, True,
     "Twenty-plus polyps of pink skirts and green centres. Beginner bulletproof."),
    ("Deep Current Leather", "Sarcophyton sp.", "Soft corals", 65, None, "torch",
     "beginner", "low", "medium", "middle", True, False,
     "Classic toadstool that needs nothing but light and time."),
    ("Ember Ridge Favia", "Favia sp.", "LPS", 130, None, "acan",
     "beginner", "low", "low", "bottom", True, True,
     "Red-on-green favia with strong feeder tentacles at night."),
    ("Sunburst Goniopora", "Goniopora stokesi", "LPS", 165, 199, "torch",
     "intermediate", "medium", "low", "bottom", True, True,
     "Long-polyp gonio in gold and pink. Feed weekly and it takes over the sand bed."),
    ("Violet Static Monti", "Montipora capricornis", "SPS", 95, None, "acro",
     "intermediate", "high", "medium", "middle", True, True,
     "Purple-rimmed plating cap. Grows into a table fast."),
    ("Ghost Anemone Frag", "Discosoma sp.", "Soft corals", 45, None, "zoa",
     "beginner", "low", "low", "bottom", True, False,
     "Metallic mushroom that splits happily in a mature tank."),
]

FISH = [
    ("Blue Hippo Tang", "Paracanthurus hepatus", "Tangs", 189, None, "peaceful", "yes",
     "Herbivore — nori sheets daily", '6 inches', 125, False,
     "Eating pellets and nori in quarantine for three weeks."),
    ("Yellow Tang", "Zebrasoma flavescens", "Tangs", 165, 199, "semi", "yes",
     "Herbivore — algae and nori", '7 inches', 125, True,
     "Aquacultured, reef-raised and grazing on film algae already."),
    ("Ocellaris Clownfish (pair)", "Amphiprion ocellaris", "Clownfish", 89, None, "peaceful", "yes",
     "Omnivore — pellets, mysis", '3 inches', 20, True,
     "Captive-bred bonded pair, hosting a rock flower anemone at the shop."),
    ("Melanurus Wrasse", "Halichoeres melanurus", "Wrasses", 74, None, "peaceful", "caution",
     "Carnivore — mysis, brine, pods", '5 inches', 55, False,
     "Best pest-control wrasse we stock. Needs a sand bed to sleep in."),
    ("Royal Gramma", "Gramma loreto", "Wrasses", 52, 68, "peaceful", "yes",
     "Carnivore — mysis and pellets", '3 inches', 30, False,
     "Purple-to-gold basslet that holds a cave and stays out of trouble."),
]

INVERTS = [
    ("Fire Shrimp", "Lysmata debelius", "Shrimp & crabs", 64, None, "Scavenger", '2 inches', 30,
     "Blood-red cleaner shrimp that will take food from your hand within a week."),
    ("Tuxedo Urchin", "Mespilia globulus", "Clean-up crew", 38, None, "Algae grazer", '3 inches', 30,
     "Relentless on film algae. Will redecorate your frag rack."),
    ("Trochus Snail (10 pack)", "Trochus sp.", "Clean-up crew", 34, 42, "Algae grazer", '1 inch', 20,
     "Rights itself when it falls, unlike the cheap alternatives."),
]

GEAR = [
    ("Rift LED Reef Light", "Lighting", 549, 649,
     "Full-spectrum 130W fixture with a coral-realistic blue channel. Covers a 24 inch cube."),
    ("Reef Crystals Salt — 200gal", "Salt & additives", 89, None,
     "The salt we mix for every system in the building."),
    ("Alkalinity Test Kit", "Test kits", 34, None,
     "Titration kit accurate to 0.1 dKH. The one number you cannot guess."),
    ("Two-Part Calcium & Alk Set", "Salt & additives", 64, 79,
     "One gallon each. Enough dosing for a 90 gallon system for roughly four months."),
    ("Coral Frag Rack (24 plug)", "Lighting", 42, None,
     "Magnetic acrylic rack that holds standard plugs without tipping."),
]

ACCLIMATION = (
    "Float the sealed bag for 15 minutes to equalise temperature, then drip acclimate at "
    "2-3 drops per second for 45 minutes. Dip corals in your preferred coral dip before they "
    "touch the display rock. Never pour shipping water into the tank."
)


class Command(BaseCommand):
    help = "Seed the store with demo categories, products, pages and imagery."

    def add_arguments(self, parser):
        parser.add_argument(
            "--flush",
            action="store_true",
            help="Delete existing catalog and content before seeding.",
        )
        parser.add_argument(
            "--no-images",
            action="store_true",
            help="Skip generating placeholder imagery (much faster).",
        )
        parser.add_argument(
            "--admin-password",
            default="",
            help="Create/refresh an 'admin' superuser with this password.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        self.rng = random.Random(20260917)
        self.make_images = not options["no_images"]

        if options["flush"]:
            self.stdout.write("Clearing existing catalog and content...")
            for model in (
                Review, BundleItem, ProductVariant, ProductVideo,
                CollectionItem, ProductImage, Product, Collection, Category, Tag,
                Article,
                HeroSlide, HomepageSection, Page, FaqItem, NavigationLink,
                LiveSaleEvent, Testimonial,
            ):
                model.objects.all().delete()

        categories = self.seed_categories()
        products = self.seed_products(categories)
        self.seed_variants(products)
        self.seed_bundles(categories, products)
        self.seed_reviews(products)
        self.seed_rewards()
        self.seed_collections(products)
        self.seed_content()
        self.seed_articles()
        self.seed_admin(options["admin_password"])

        self.stdout.write(self.style.SUCCESS(
            f"Seeded {Product.objects.count()} products across "
            f"{Category.objects.count()} categories."
        ))

    # --- catalog ---------------------------------------------------------
    def seed_categories(self):
        lookup = {}
        for order, (name, ptype, palette, blurb, children) in enumerate(CATEGORIES):
            parent, _ = Category.objects.get_or_create(
                name=name,
                parent=None,
                defaults={
                    "product_type": ptype,
                    "description": blurb,
                    "sort_order": order,
                },
            )
            self.attach_image(parent, "image", f"cat-{name}", palette, (900, 700))
            lookup[name] = parent
            for child_order, (child_name, child_palette) in enumerate(children):
                child, _ = Category.objects.get_or_create(
                    name=child_name,
                    parent=parent,
                    defaults={"product_type": ptype, "sort_order": child_order},
                )
                self.attach_image(child, "image", f"cat-{child_name}", child_palette, (900, 700))
                lookup[child_name] = child
        return lookup

    def seed_products(self, categories):
        created = []
        tags = {
            name: Tag.objects.get_or_create(name=name)[0]
            for name in [
                "WYSIWYG", "Aquacultured", "Captive bred", "Beginner friendly",
                "Show piece", "Live sale", "Staff pick",
            ]
        }
        now = timezone.now()

        for index, row in enumerate(CORALS):
            (name, sci, cat, price, was, palette, care, light, flow, place,
             aqua, wysiwyg, description) = row
            product = self.upsert_product(
                name=name,
                category=categories[cat],
                product_type=ProductType.CORAL,
                scientific_name=sci,
                price=price,
                compare_at_price=was,
                description=description,
                defaults={
                    "care_level": care,
                    "lighting": light,
                    "flow": flow,
                    "placement": place,
                    "is_aquacultured": aqua,
                    "is_wysiwyg": wysiwyg,
                    "acclimation_notes": ACCLIMATION,
                    "tagline": "Grown in our greenhouse system under Radion lighting."
                    if aqua else "Hand-selected import, fully settled.",
                    "stock_quantity": 1 if wysiwyg else self.rng.randint(0, 8),
                    "is_featured": index < 4,
                    "published_at": now - timedelta(days=index),
                },
            )
            product.tags.add(tags["Aquacultured"] if aqua else tags["Show piece"])
            if wysiwyg:
                product.tags.add(tags["WYSIWYG"])
            if care == "beginner":
                product.tags.add(tags["Beginner friendly"])
            self.attach_product_images(product, palette, count=3 if wysiwyg else 2)
            created.append(product)

        for index, row in enumerate(FISH):
            (name, sci, cat, price, was, temperament, reef_safe, diet, max_size,
             tank, captive, description) = row
            product = self.upsert_product(
                name=name,
                category=categories[cat],
                product_type=ProductType.FISH,
                scientific_name=sci,
                price=price,
                compare_at_price=was,
                description=description,
                defaults={
                    "care_level": CareLevel.INTERMEDIATE,
                    "temperament": temperament,
                    "reef_safe": reef_safe,
                    "diet": diet,
                    "max_size": max_size,
                    "min_tank_size_gallons": tank,
                    "is_captive_bred": captive,
                    "acclimation_notes": ACCLIMATION,
                    "tagline": "Quarantined for 21 days and eating prepared food.",
                    "stock_quantity": self.rng.randint(0, 5),
                    "is_featured": index < 2,
                    "published_at": now - timedelta(days=index + 2),
                },
            )
            if captive:
                product.tags.add(tags["Captive bred"])
            self.attach_product_images(product, "fish", count=2)
            created.append(product)

        for index, row in enumerate(INVERTS):
            name, sci, cat, price, was, diet, max_size, tank, description = row
            product = self.upsert_product(
                name=name,
                category=categories[cat],
                product_type=ProductType.INVERT,
                scientific_name=sci,
                price=price,
                compare_at_price=was,
                description=description,
                defaults={
                    "care_level": CareLevel.BEGINNER,
                    "diet": diet,
                    "max_size": max_size,
                    "min_tank_size_gallons": tank,
                    "reef_safe": ReefSafe.YES,
                    "acclimation_notes": ACCLIMATION,
                    "stock_quantity": self.rng.randint(2, 12),
                    "published_at": now - timedelta(days=index + 3),
                },
            )
            self.attach_product_images(product, "invert", count=1)
            created.append(product)

        for index, (name, cat, price, was, description) in enumerate(GEAR):
            product = self.upsert_product(
                name=name,
                category=categories[cat],
                product_type=ProductType.DRY_GOODS,
                scientific_name="",
                price=price,
                compare_at_price=was,
                description=description,
                defaults={
                    "stock_quantity": self.rng.randint(3, 25),
                    "published_at": now - timedelta(days=index + 4),
                },
            )
            self.attach_product_images(product, "gear", count=1)
            created.append(product)

        return created

    def upsert_product(self, *, name, category, product_type, scientific_name,
                       price, compare_at_price, description, defaults=None):
        values = {
            "category": category,
            "product_type": product_type,
            "scientific_name": scientific_name,
            "price": Decimal(str(price)),
            "compare_at_price": Decimal(str(compare_at_price)) if compare_at_price else None,
            "description": description,
            "status": Product.Status.ACTIVE,
            **(defaults or {}),
        }
        product, created = Product.objects.get_or_create(name=name, defaults=values)
        if not created:
            for field, value in values.items():
                setattr(product, field, value)
            product.save()
        return product

    def attach_product_images(self, product, palette, count=2):
        if not self.make_images or product.images.exists():
            return
        for i in range(count):
            image = ProductImage(
                product=product,
                alt_text=f"{product.name} under reef lighting",
                caption="Photographed under 20k blues in our display system" if i == 0 else "",
                is_primary=(i == 0),
                sort_order=i,
            )
            image.image.save(
                f"{product.slug}-{i + 1}.jpg",
                generate_image(f"{product.slug}-{i}", palette),
                save=False,
            )
            image.save()

    def attach_image(self, obj, field, seed, palette, size, style="colony"):
        if not self.make_images or getattr(obj, field):
            return
        getattr(obj, field).save(
            f"{seed}.jpg", generate_image(seed, palette, size=size, style=style), save=True
        )

    def seed_variants(self, products):
        """Give a few corals frag/colony options and a pack-size dry good."""
        specs = {
            "Bioluminescent Hammer": [
                ("Single head", "275.00", 4, True),
                ("Three head colony", "740.00", 1, False),
            ],
            "Nebula Zoa Garden": [
                ("5 polyp frag", "85.00", 6, True),
                ("15+ polyp colony", "210.00", 2, False),
            ],
            "Reef Crystals Salt — 200gal": [
                ("50 gallon box", "34.00", 20, True),
                ("200 gallon box", "89.00", 9, False),
            ],
        }
        by_name = {p.name: p for p in products}
        for name, options in specs.items():
            product = by_name.get(name)
            if product is None or product.variants.exists():
                continue
            for order, (label, price, stock, is_default) in enumerate(options):
                ProductVariant.objects.create(
                    product=product, name=label, price=Decimal(price),
                    stock_quantity=stock, is_default=is_default, sort_order=order,
                )

        # A video on the headline WYSIWYG piece.
        torch = by_name.get("Midnight Torch")
        if torch and not torch.videos.exists():
            ProductVideo.objects.create(
                product=torch,
                title="Midnight Torch under 20k blues",
                url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            )

    def seed_bundles(self, categories, products):
        by_name = {p.name: p for p in products}
        pack, created = Product.objects.get_or_create(
            name="Beginner Four Pack",
            defaults={
                "category": categories["Corals"],
                "product_type": ProductType.BUNDLE,
                "price": Decimal("199.00"),
                "compare_at_price": Decimal("265.00"),
                "description": "Four forgiving corals chosen to survive a young tank: "
                               "a zoa garden, a leather, a favia and a mushroom.",
                "tagline": "Four beginner corals, one box, one shipping charge.",
                "status": Product.Status.ACTIVE,
                "stock_quantity": 8,
                "bundle_size": 4,
                "is_featured": True,
            },
        )
        if created:
            self.attach_product_images(pack, "zoa", count=1)
            for order, name in enumerate(
                ["Nebula Zoa Garden", "Deep Current Leather", "Ember Ridge Favia", "Ghost Anemone Frag"]
            ):
                item = by_name.get(name)
                if item:
                    BundleItem.objects.get_or_create(
                        bundle=pack, product=item, defaults={"sort_order": order}
                    )

        mystery, created = Product.objects.get_or_create(
            name="Mystery Coral Box",
            defaults={
                "category": categories["Corals"],
                "product_type": ProductType.BUNDLE,
                "price": Decimal("249.00"),
                "description": "Five named corals picked on packing day from whatever is "
                               "colouring up best. Always worth more than the box price.",
                "tagline": "Five pieces, our choice, never a dud.",
                "status": Product.Status.ACTIVE,
                "stock_quantity": 12,
                "is_mystery": True,
                "bundle_size": 5,
            },
        )
        if created:
            self.attach_product_images(mystery, "chalice", count=1)

    def seed_reviews(self, products):
        samples = [
            ("Midnight Torch", 5, "Arrived fully extended",
             "Overnight in January and it opened within an hour of acclimation. "
             "The heat pack placement tells you these people keep reefs themselves.",
             "Dana R.", True),
            ("Midnight Torch", 4, "Beautiful, slow to settle",
             "Took about ten days to fully extend, which is normal. Colour matches "
             "the listing photo exactly.", "Marcus T.", True),
            ("Rift Fire Acan Lord", 5, "Photo was honest",
             "What showed up was the coral in the picture, same size, same colour, "
             "no wide-angle lens tricks.", "Priya S.", True),
            ("Yellow Tang", 5, "Eating from day one",
             "Went straight for the nori. Clearly quarantined properly.",
             "Chris M.", False),
        ]
        by_name = {p.name: p for p in products}
        for name, rating, title, body, author, verified in samples:
            product = by_name.get(name)
            if product is None:
                continue
            Review.objects.get_or_create(
                product=product, author_name=author,
                defaults={
                    "rating": rating, "title": title, "body": body,
                    "author_email": f"{slugify(author)}@example.com",
                    "is_verified_purchase": verified,
                    "status": Review.Status.APPROVED,
                    "published_at": timezone.now(),
                },
            )

    def seed_rewards(self):
        RewardsSettings.load()
        DiscountCode.objects.get_or_create(
            code="REEF10",
            defaults={
                "kind": DiscountCode.Kind.PERCENT,
                "value": Decimal("10.00"),
                "description": "10% off your first order.",
                "max_uses_per_customer": 1,
            },
        )
        DiscountCode.objects.get_or_create(
            code="FREESHIP299",
            defaults={
                "kind": DiscountCode.Kind.FREE_SHIPPING,
                "description": "Free overnight shipping.",
                "minimum_subtotal": Decimal("299.00"),
            },
        )
        if not GiftCard.objects.exists():
            GiftCard.objects.create(
                initial_balance=Decimal("100.00"),
                message="Demo gift card — try it at checkout.",
            )

    def seed_articles(self):
        articles = [
            ("Why your new coral is closed up (and why that's fine)", Article.Category.CARE,
             "Shipping stress looks alarming and almost never is.",
             "<p>A coral that travelled overnight has spent eighteen hours in the dark in a bag "
             "of its own waste. Staying retracted for two or three days afterwards is the normal "
             "response, not a warning sign.</p>"
             "<h2>What to do</h2><ul>"
             "<li>Dim the lights for the first 48 hours.</li>"
             "<li>Put it low, in moderate flow, and leave it there.</li>"
             "<li>Do not feed it, do not dip it twice, do not keep moving it.</li></ul>"
             "<p>Judge a new coral after a week. Most of the losses we see are from people "
             "intervening on day two.</p>"),
            ("Drip acclimation, step by step", Article.Category.HOWTO,
             "Fifteen minutes of patience saves a $300 colony.",
             "<p>Shipping water is ammonia-heavy by the time it lands. Acclimation is about "
             "matching pH and salinity, not about keeping that water.</p>"
             "<h2>The method</h2><ol>"
             "<li>Float the sealed bag for 15 minutes.</li>"
             "<li>Open it into a clean container and drip at 2–3 drops per second.</li>"
             "<li>After 45 minutes, net the animal across. Discard the shipping water.</li></ol>"),
            ("Torch corals: the honest care guide", Article.Category.SPECIES,
             "Euphyllia are forgiving until they aren't.",
             "<p>Torches want moderate light, moderate flow, and to be left alone. The two "
             "things that kill them are aggressive neighbours and unstable alkalinity.</p>"
             "<h2>Placement</h2><p>Give a torch 6 inches of clearance in every direction. "
             "Their sweepers reach further than people expect, and they lose fights with "
             "hammers less often than the internet claims.</p>"),
        ]
        for order, (title, category, summary, body) in enumerate(articles):
            Article.objects.get_or_create(
                title=title,
                defaults={
                    "category": category,
                    "summary": summary,
                    "body": body,
                    "author": "The livestock team",
                    "published_at": timezone.now() - timedelta(days=order * 6),
                },
            )

    def seed_collections(self, products):
        specs = [
            ("WYSIWYG Coral Vault", "Every piece one of one, photographed as it sits today.",
             [p for p in products if p.is_wysiwyg], "acro", True),
            ("Beginner Reef Starters", "Forgiving corals and fish that tolerate a young tank.",
             [p for p in products if p.care_level == CareLevel.BEGINNER], "zoa", True),
            ("Under $100", "Frags and gear that leave room in the budget for salt.",
             [p for p in products if p.price < 100], "torch", False),
        ]
        for order, (title, subtitle, items, palette, on_home) in enumerate(specs):
            collection, _ = Collection.objects.get_or_create(
                title=title,
                defaults={
                    "subtitle": subtitle,
                    "show_on_homepage": on_home,
                    "sort_order": order,
                },
            )
            self.attach_image(collection, "image", f"col-{collection.slug}", palette, (1200, 700), "scene")
            for position, product in enumerate(items[:12]):
                CollectionItem.objects.get_or_create(
                    collection=collection, product=product,
                    defaults={"sort_order": position},
                )

    # --- content ---------------------------------------------------------
    def seed_content(self):
        site = SiteSettings.load()
        site.store_name = "Reef & Rift"
        site.tagline = "Aquacultured corals, quarantined fish, shipped overnight."
        site.contact_email = "hello@reefandrift.example"
        site.contact_phone = "(555) 018-7745"
        site.address = "1420 Tidewater Ave\nSuite 3\nWilmington, NC 28401"
        site.hours = "Tue–Sat, 11am–6pm ET"
        site.instagram_url = "https://instagram.com/example"
        site.youtube_url = "https://youtube.com/@example"
        site.save()

        slide, _ = HeroSlide.objects.get_or_create(
            headline="Corals grown here, not just shipped here.",
            defaults={
                "eyebrow": "Aquacultured in North Carolina",
                "subhead": "Every frag on this site was cut from a mother colony in our own "
                           "greenhouse system, settled for 30 days, and photographed the "
                           "morning it went up for sale.",
                "cta_label": "Shop corals",
                "cta_url": "/category/corals/",
                "secondary_cta_label": "How shipping works",
                "secondary_cta_url": "/pages/shipping/",
            },
        )
        self.attach_image(slide, "image", "hero-main", "scene", (1800, 1000), "scene")

        sections = [
            (HomepageSection.Kind.GUARANTEE, "", "", 0, None),
            (HomepageSection.Kind.WYSIWYG, "WYSIWYG vault",
             "What you see is the exact colony that ships to you.", 1, 8),
            (HomepageSection.Kind.CATEGORY_GRID, "Shop by category", "", 2, None),
            (HomepageSection.Kind.FEATURED, "Staff picks this week",
             "What the livestock team is watching in the frag system.", 3, 8),
            (HomepageSection.Kind.ON_SALE, "On sale", "Markdowns on healthy, settled stock.", 4, 4),
            (HomepageSection.Kind.RICH_TEXT, "Why aquacultured matters", "", 5, None),
            (HomepageSection.Kind.TESTIMONIALS, "From the reefkeepers", "", 6, None),
            (HomepageSection.Kind.NEW_ARRIVALS, "Just added",
             "Fresh out of quarantine and onto the sales rack.", 7, 8),
        ]
        for kind, heading, subheading, order, limit in sections:
            defaults = {
                "heading": heading,
                "subheading": subheading,
                "sort_order": order,
                "max_items": limit or 8,
            }
            if kind == HomepageSection.Kind.RICH_TEXT:
                defaults["body"] = (
                    "A wild colony takes decades to grow and minutes to remove. Aquacultured "
                    "coral takes months, arrives already adapted to aquarium lighting and "
                    "flow, and carries far less risk of importing pests into your display.\n\n"
                    "Roughly 80% of what we sell was fragged in-house from colonies we have "
                    "kept for years. The rest comes from farms and importers we have visited "
                    "in person. Anything wild-collected is labelled as such on its listing."
                )
                defaults["cta_label"] = "Read our sourcing policy"
                defaults["cta_url"] = "/pages/sourcing/"
            if kind == HomepageSection.Kind.WYSIWYG:
                defaults["cta_label"] = "See the vault"
                defaults["cta_url"] = "/shop/?wysiwyg=1"
            HomepageSection.objects.get_or_create(kind=kind, defaults=defaults)

        pages = [
            ("Live Arrival Guarantee", "Every animal is covered for 8 hours after delivery.",
             "<p>We guarantee that every animal arrives alive. If something does not, we credit it "
             "in full — no arguing about whether a polyp looked retracted.</p>"
             "<h2>How to file a claim</h2><ol>"
             "<li>Photograph the animal <strong>in the sealed bag</strong> it arrived in, before you open it.</li>"
             "<li>Open your order page and choose <em>File a live arrival claim</em>.</li>"
             "<li>Submit within 8 hours of the carrier's delivery scan.</li></ol>"
             "<h2>What is covered</h2><p>Every coral, fish and invertebrate we ship, at full purchase "
             "price, as store credit or a refund to the original payment method.</p>"
             "<h2>What is not</h2><ul>"
             "<li>Boxes refused or left sitting at the door after a delivery attempt.</li>"
             "<li>Shipments delivered to an address where nobody was present to receive them.</li>"
             "<li>Losses after the 8 hour window, which are a tank problem rather than a shipping one.</li>"
             "<li>Colour change or slow recovery — corals take weeks to settle and that is normal.</li></ul>", 1),
            ("Shipping", "Overnight only, Monday through Wednesday.",
             "<p>Livestock leaves our facility Monday, Tuesday and Wednesday by overnight service so "
             "nothing sits in a hub over a weekend.</p>"
             "<h2>Rates</h2><p>$59 flat for any livestock order, free over $299. Dry goods alone ship "
             "at $12 flat.</p>"
             "<h2>Weather holds</h2><p>When temperatures at either end fall outside roughly 35–95°F we "
             "hold your box and email you. Heat packs and cool packs go in automatically as needed — "
             "you do not need to ask or pay extra.</p>"
             "<h2>Receiving your box</h2><p>Someone must be present. Carriers will leave a box on a "
             "porch in any weather, and a coral that cooks on a doorstep is not covered by the "
             "guarantee.</p>", 2),
            ("Acclimation Guide", "Fifteen minutes of patience saves a $300 colony.",
             "<h2>Corals</h2><ol>"
             "<li>Dim your lights or turn them off entirely for the first day.</li>"
             "<li>Float the sealed bag for 15 minutes to match temperature.</li>"
             "<li>Dip in your preferred coral dip for the time on the bottle, then rinse in clean saltwater.</li>"
             "<li>Place low and in moderate flow. Move it up over the following two weeks, not the same day.</li></ol>"
             "<h2>Fish and inverts</h2><ol>"
             "<li>Float for 15 minutes.</li>"
             "<li>Drip acclimate at 2–3 drops per second for 45–60 minutes.</li>"
             "<li>Net the animal into the tank. Never pour shipping water into your display.</li>"
             "<li>Leave the lights off for the rest of the day and skip feeding until morning.</li></ol>"
             "<p>Shipping water is ammonia-heavy by the time it lands. The drip is about pH and "
             "salinity, not about keeping that water.</p>", 3),
            ("Sourcing", "Where our livestock actually comes from.",
             "<p>Roughly four out of five corals we sell were fragged in our own greenhouse from "
             "colonies we have grown for years. The remainder comes from a short list of farms and "
             "importers we have visited.</p>"
             "<p>Every fish spends a minimum of 21 days in quarantine, eating prepared food, before "
             "it is listed. Wild-collected animals are labelled on their listing — we do not bury "
             "that detail.</p>", 4),
            ("About", "A greenhouse, a lot of frag plugs, and no marketing department.",
             "<p>Reef &amp; Rift started as a garage frag tank in 2016 and turned into a 6,000 gallon "
             "greenhouse system. We photograph what we sell, we quarantine what swims, and we tell "
             "you when something is wild-collected.</p>"
             "<p>Every order is packed by the same people who grew the coral. If something goes "
             "wrong, you are talking to them, not a ticket queue.</p>", 5),
        ]
        for title, summary, body, order in pages:
            Page.objects.get_or_create(
                title=title,
                defaults={"summary": summary, "body": body, "sort_order": order},
            )

        faqs = [
            (FaqItem.Topic.SHIPPING, "When will my order ship?",
             "Livestock leaves Monday through Wednesday by overnight service. If you order Thursday "
             "through Sunday, your box goes out the following Monday unless you asked for a later date."),
            (FaqItem.Topic.SHIPPING, "Do you ship in winter?",
             "Yes. Heat packs go in automatically below about 50°F, and we hold the box rather than "
             "risk it when temperatures at either end are extreme."),
            (FaqItem.Topic.SHIPPING, "Can I combine orders?",
             "Yes — email us with both order numbers before either ships and we will merge them and "
             "refund the duplicate shipping."),
            (FaqItem.Topic.LIVESTOCK, "What does WYSIWYG mean?",
             "What you see is what you get: the photo is that exact colony, it is the only one, and "
             "once it sells the listing is gone."),
            (FaqItem.Topic.LIVESTOCK, "My coral looks closed up. Is it dying?",
             "Almost certainly not. Corals routinely stay retracted for two or three days after "
             "shipping. Keep the lights low, leave it alone, and judge it after a week."),
            (FaqItem.Topic.LIVESTOCK, "Are your fish quarantined?",
             "Every fish spends at least 21 days in quarantine and must be eating prepared food "
             "before we list it."),
            (FaqItem.Topic.ORDERS, "How do I file a live arrival claim?",
             "Photograph the animal in its sealed bag, then open your order page and choose 'File a "
             "live arrival claim' within 8 hours of delivery."),
            (FaqItem.Topic.ORDERS, "Can I cancel an order?",
             "Yes, any time before it ships. Once a box is packed and the label is generated we "
             "cannot pull it back."),
        ]
        for order, (topic, question, answer) in enumerate(faqs):
            FaqItem.objects.get_or_create(
                question=question,
                defaults={"topic": topic, "answer": answer, "sort_order": order},
            )

        nav = [
            ("Live sales", "/live-sales/", NavigationLink.Placement.HEADER, 0),
            ("WYSIWYG", "/shop/?wysiwyg=1", NavigationLink.Placement.HEADER, 1),
            ("Guarantee", "/pages/live-arrival-guarantee/", NavigationLink.Placement.HEADER, 2),
            ("On sale", "/shop/?sale=1", NavigationLink.Placement.FOOTER_SHOP, 0),
            ("New arrivals", "/shop/?sort=newest", NavigationLink.Placement.FOOTER_SHOP, 1),
        ]
        for label, url, placement, order in nav:
            NavigationLink.objects.get_or_create(
                label=label, placement=placement,
                defaults={"url": url, "sort_order": order},
            )

        event, _ = LiveSaleEvent.objects.get_or_create(
            title="Friday Night Frag Fest",
            defaults={
                "description": "Two hours of cutting from the display system, streamed live. "
                               "Claim in chat, we invoice after the stream and ship Monday.",
                "starts_at": timezone.now() + timedelta(days=5, hours=3),
                "ends_at": timezone.now() + timedelta(days=5, hours=5),
                "stream_url": "https://youtube.com/@example/live",
                "collection": Collection.objects.filter(title="WYSIWYG Coral Vault").first(),
            },
        )
        self.attach_image(event, "image", "event-fragfest", "chalice", (1200, 800), "scene")

        testimonials = [
            ("Six torch heads arrived fully extended after an overnight in January. "
             "The heat pack placement alone tells you these people actually keep reefs.",
             "Dana R.", "Minneapolis, MN", 5),
            ("The WYSIWYG photos are honest. What showed up was the coral in the picture, "
             "same size, same colour, no wide-angle lens tricks.", "Marcus T.", "Austin, TX", 5),
            ("One shrimp arrived DOA, I filed the claim with a bag photo, and the credit "
             "landed the same afternoon. No argument.", "Priya S.", "Seattle, WA", 5),
        ]
        for order, (quote, author, location, rating) in enumerate(testimonials):
            Testimonial.objects.get_or_create(
                author=author,
                defaults={"quote": quote, "location": location,
                          "rating": rating, "sort_order": order},
            )

    def seed_admin(self, password):
        if not password:
            return
        User = get_user_model()
        user, created = User.objects.get_or_create(
            username="admin", defaults={"email": "admin@reefandrift.example"}
        )
        user.is_staff = True
        user.is_superuser = True
        user.set_password(password)
        user.save()
        verb = "Created" if created else "Updated"
        self.stdout.write(self.style.SUCCESS(f"{verb} superuser 'admin'."))
