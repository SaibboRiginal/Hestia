"""Idealista.it listing enrichment handler.

Extracts structured data from Idealista listing pages using reliable
sources: JSON-LD microdata, OpenGraph/meta tags, and known DOM selectors.
The LLM handles primary extraction; this handler augments with page data.
"""

import json
import re
from typing import Optional
from urllib.parse import urlparse, urlunparse

from bs4 import BeautifulSoup

from worker.sites.base import BaseSiteHandler


class IdealistaSiteHandler(BaseSiteHandler):
    """Enrichment handler for ``idealista.it`` listings."""

    @property
    def site_name(self) -> str:
        return "idealista"

    def can_handle(self, url: str) -> bool:
        return "idealista.it" in str(url).lower()

    def normalize_url(self, url: str) -> str:
        try:
            parsed = urlparse(str(url).strip())
            clean_path = parsed.path.rstrip("/")
            return urlunparse((
                parsed.scheme,
                parsed.netloc.lower(),
                clean_path,
                "", "", "",
            ))
        except Exception:
            return str(url).strip()

    # ------------------------------------------------------------------ #
    #  Public enrichment entry point                                      #
    # ------------------------------------------------------------------ #

    def enrich(self, soup: BeautifulSoup, payload: dict) -> dict:
        enriched = dict(payload)
        enriched["source_site"] = self.site_name
        specs = dict(enriched.get("specs") or {})
        extras = dict(enriched.get("extras") or {})

        enriched, specs = self._extract_json_ld(soup, enriched, specs)
        enriched = self._extract_meta_tags(soup, enriched)
        enriched, specs, extras = self._extract_primary_dom_facts(
            soup, enriched, specs, extras)
        enriched, specs, extras = self._extract_details_box_facts(
            soup, enriched, specs, extras)
        enriched, extras = self._extract_price_panel_facts(
            soup, enriched, extras)
        enriched, extras = self._extract_location_panel_facts(
            soup, enriched, extras)
        enriched, extras = self._extract_agency_facts(soup, enriched, extras)
        enriched = self._extract_description(soup, enriched)
        enriched, specs = self._extract_textual_fallbacks(
            soup, enriched, specs)
        enriched = self._extract_address(soup, enriched)
        enriched, extras = self._extract_structured_characteristics(
            soup, enriched, extras)
        enriched = self._compose_common_sections(enriched, specs, extras)

        if specs:
            enriched["specs"] = specs
        if extras:
            enriched["extras"] = extras
        return enriched

    def _compose_common_sections(self, enriched: dict, specs: dict, extras: dict) -> dict:
        pricing = dict(enriched.get("pricing") or {})
        if enriched.get("price") is not None:
            pricing["price"] = enriched.get("price")
        if extras.get("price_per_m2") is not None:
            pricing["price_per_m2"] = extras.get("price_per_m2")
        if extras.get("condo_fees"):
            pricing["condo_fees"] = extras.get("condo_fees")
        if extras.get("condo_fees_monthly_eur") is not None:
            pricing["condo_fees_monthly_eur"] = extras.get("condo_fees_monthly_eur")
        if pricing:
            enriched["pricing"] = pricing

        energy = dict(enriched.get("energy") or {})
        if extras.get("year_built") is not None:
            energy["year_built"] = extras.get("year_built")
        if extras.get("property_state"):
            energy["property_state"] = extras.get("property_state")
        if specs.get("heating"):
            energy["heating"] = specs.get("heating")
        if extras.get("climatization"):
            energy["climatization"] = extras.get("climatization")
        if energy:
            enriched["energy"] = energy

        contact = dict(enriched.get("contact") or {})
        if extras.get("reference_id"):
            contact["reference_id"] = extras.get("reference_id")
        if extras.get("agent_name"):
            contact["agent_name"] = extras.get("agent_name")
        if extras.get("agency_name"):
            contact["agency_name"] = extras.get("agency_name")
        if extras.get("updated_text"):
            contact["updated_text"] = extras.get("updated_text")
        if contact:
            enriched["contact"] = contact

        return enriched

    def _extract_structured_characteristics(
        self,
        soup: BeautifulSoup,
        enriched: dict,
        extras: dict,
    ) -> tuple[dict, dict]:
        characteristics: dict[str, str] = dict(enriched.get("characteristics") or {})

        for li in soup.select("section#details .details-property_features li"):
            text = li.get_text(" ", strip=True)
            if not text:
                continue
            if ":" in text:
                key, value = text.split(":", 1)
                key = key.strip()
                value = value.strip()
                if key and value:
                    characteristics[key] = value
            else:
                # Keep non key-value features in a predictable bucket.
                characteristics.setdefault("Altre", "")
                existing = characteristics["Altre"]
                if text not in existing.split(" | "):
                    characteristics["Altre"] = f"{existing} | {text}".strip(" |")

        if characteristics:
            enriched["characteristics"] = characteristics
            extras["characteristics_count"] = len(characteristics)

        return enriched, extras

    # ------------------------------------------------------------------ #
    #  JSON-LD extraction                                                 #
    # ------------------------------------------------------------------ #

    def _extract_json_ld(
        self,
        soup: BeautifulSoup,
        enriched: dict,
        specs: dict,
    ) -> tuple[dict, dict]:
        for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
            raw = (script.string or "").strip()
            if not raw:
                continue
            try:
                data = json.loads(raw)
                items = (
                    [data] if isinstance(data, dict)
                    else data if isinstance(data, list)
                    else []
                )
            except Exception:
                continue

            for item in items:
                if not isinstance(item, dict):
                    continue

                if not enriched.get("title") and item.get("name"):
                    enriched["title"] = str(item["name"]).strip()

                if item.get("description"):
                    enriched["summary"] = self._prefer_summary(
                        enriched.get("summary", ""),
                        str(item["description"]).strip(),
                    )

                address = item.get("address")
                if isinstance(address, dict):
                    self._apply_structured_address(address, enriched)

                self._apply_ld_specs(item, specs)

                offers = item.get("offers")
                if not enriched.get("price") and isinstance(offers, dict):
                    val = self._to_int(offers.get("price"))
                    if val:
                        enriched["price"] = val

        return enriched, specs

    def _apply_ld_specs(self, item: dict, specs: dict) -> None:
        if "rooms" not in specs and item.get("numberOfRooms") is not None:
            val = self._to_int(item["numberOfRooms"])
            if val:
                specs["rooms"] = val

        if "bathrooms" not in specs and item.get("numberOfBathroomsTotal") is not None:
            val = self._to_int(item["numberOfBathroomsTotal"])
            if val:
                specs["bathrooms"] = val

        if "surface_m2" not in specs and item.get("floorSize") is not None:
            floor_size = item["floorSize"]
            raw = floor_size.get("value") if isinstance(
                floor_size, dict) else floor_size
            val = self._to_int(raw)
            if val:
                specs["surface_m2"] = val

    def _apply_structured_address(self, address: dict, enriched: dict) -> None:
        parts = [
            str(address.get(k) or "").strip()
            for k in (
                "streetAddress",
                "addressLocality",
                "addressRegion",
                "postalCode",
                "addressCountry",
            )
        ]
        full = ", ".join(p for p in parts if p)
        if full and len(full) > len(str(enriched.get("address", "")).strip()):
            enriched["address"] = full

    # ------------------------------------------------------------------ #
    #  Meta tags                                                          #
    # ------------------------------------------------------------------ #

    def _extract_meta_tags(self, soup: BeautifulSoup, enriched: dict) -> dict:
        og_desc = soup.find("meta", attrs={"property": "og:description"})
        if og_desc and og_desc.get("content"):
            enriched["summary"] = self._prefer_summary(
                enriched.get("summary", ""),
                str(og_desc["content"]).strip(),
            )

        meta_desc = soup.find("meta", attrs={"name": "description"})
        if meta_desc and meta_desc.get("content"):
            enriched["summary"] = self._prefer_summary(
                enriched.get("summary", ""),
                str(meta_desc["content"]).strip(),
            )

        og_url = soup.find("meta", attrs={"property": "og:url"})
        if og_url and og_url.get("content") and not enriched.get("url"):
            enriched["url"] = self.normalize_url(
                str(og_url["content"]).strip())

        og_image = soup.find("meta", attrs={"property": "og:image"})
        if og_image and og_image.get("content") and not enriched.get("image"):
            enriched["image"] = str(og_image["content"]).strip()

        og_title = soup.find("meta", attrs={"property": "og:title"})
        if og_title and og_title.get("content") and not enriched.get("title"):
            raw = str(og_title["content"]).strip()
            enriched["title"] = re.split(
                r"\s+[—-]\s+idealista", raw, maxsplit=1, flags=re.IGNORECASE,
            )[0].strip() or raw

        if not str(enriched.get("address", "")).strip():
            self._extract_address_from_meta(soup, enriched)

        if not enriched.get("price"):
            for source in [
                str(og_desc.get("content") or "") if og_desc else "",
                str(meta_desc.get("content") or "") if meta_desc else "",
            ]:
                val = self._extract_money_int(source)
                if val is not None:
                    enriched["price"] = val
                    break

        return enriched

    def _extract_primary_dom_facts(
        self,
        soup: BeautifulSoup,
        enriched: dict,
        specs: dict,
        extras: dict,
    ) -> tuple[dict, dict, dict]:
        # Main title/address blocks.
        title_main = soup.select_one("span.main-info__title-main")
        if title_main:
            title_text = title_main.get_text(" ", strip=True)
            if title_text:
                enriched["title"] = title_text

        title_minor = soup.select_one("span.main-info__title-minor")
        if title_minor and not str(enriched.get("address", "")).strip():
            candidate = title_minor.get_text(" ", strip=True)
            if candidate and len(candidate) > 2:
                enriched["address"] = candidate

        # Price block.
        if not enriched.get("price"):
            for selector in ["strong.price", "span.info-data-price", ".price-feature strong.flex-feature-details"]:
                node = soup.select_one(selector)
                if node:
                    value = self._extract_money_int(
                        node.get_text(" ", strip=True))
                    if value is not None:
                        enriched["price"] = value
                        break

        # Compact top feature chips (e.g. "75 m2", "2 locali", "1º piano").
        for node in soup.select("div.info-features span"):
            text = node.get_text(" ", strip=True)
            self._apply_feature_text(text, specs, extras)

        # Listing id from URL.
        normalized = self.normalize_url(str(enriched.get("url", "")).strip())
        if normalized:
            match = re.search(r"/immobile/(\d+)", normalized)
            if match:
                extras.setdefault("listing_id", match.group(1))

        return enriched, specs, extras

    def _extract_details_box_facts(
        self,
        soup: BeautifulSoup,
        enriched: dict,
        specs: dict,
        extras: dict,
    ) -> tuple[dict, dict, dict]:
        # "Caratteristiche specifiche" and "Costruzione" sections.
        for li in soup.select("section#details .details-property_features li"):
            text = li.get_text(" ", strip=True)
            if not text:
                continue
            self._apply_feature_text(text, specs, extras)

        # Updated info.
        update_p = soup.select_one(
            "section.date-update-block p.time-since-last-modification")
        if update_p:
            extras.setdefault("updated_relative",
                              update_p.get_text(" ", strip=True))

        stats_p = soup.select_one("#stats p.stats-text")
        if stats_p:
            extras.setdefault(
                "updated_text", stats_p.get_text(" ", strip=True))

        return enriched, specs, extras

    def _extract_price_panel_facts(
        self,
        soup: BeautifulSoup,
        enriched: dict,
        extras: dict,
    ) -> tuple[dict, dict]:
        # Dedicated "Prezzo" panel has authoritative values.
        for row in soup.select(".price-feature .flex-feature"):
            key_node = row.select_one("span.flex-feature-details")
            val_node = row.select_one(
                "strong.flex-feature-details, span.flex-feature-details:last-child")
            if not key_node or not val_node:
                continue
            key = key_node.get_text(" ", strip=True).lower()
            val_text = val_node.get_text(" ", strip=True)

            if "prezzo dell'immobile" in key:
                value = self._extract_money_int(val_text)
                if value is not None:
                    enriched["price"] = value
            elif "prezzo al m" in key:
                value = self._extract_money_int(val_text)
                if value is not None:
                    extras["price_per_m2"] = value

        return enriched, extras

    def _extract_location_panel_facts(
        self,
        soup: BeautifulSoup,
        enriched: dict,
        extras: dict,
    ) -> tuple[dict, dict]:
        parts = [
            li.get_text(" ", strip=True)
            for li in soup.select("#mapWrapper .header-map-list")
            if li.get_text(" ", strip=True)
        ]
        if parts:
            full = ", ".join(parts)
            if not str(enriched.get("address", "")).strip() or len(full) > len(str(enriched.get("address", "")).strip()):
                enriched["address"] = full
            if len(parts) > 1:
                extras.setdefault("city", parts[1])
            if len(parts) > 2:
                extras.setdefault("area", parts[2])
        return enriched, extras

    def _extract_agency_facts(
        self,
        soup: BeautifulSoup,
        enriched: dict,
        extras: dict,
    ) -> tuple[dict, dict]:
        agency = soup.select_one("p.advertiser-name")
        if agency:
            extras.setdefault("agency_name", agency.get_text(" ", strip=True))

        contact_title = soup.select_one(".module-contact_title strong")
        if contact_title:
            extras.setdefault(
                "contact_label", contact_title.get_text(" ", strip=True))

        return enriched, extras

    def _extract_textual_fallbacks(
        self,
        soup: BeautifulSoup,
        enriched: dict,
        specs: dict,
    ) -> tuple[dict, dict]:
        text = soup.get_text(" ", strip=True)

        if not enriched.get("price"):
            price = self._extract_money_int(text)
            if price is not None:
                enriched["price"] = price

        if "surface_m2" not in specs:
            m = re.search(
                r"(\d+(?:[\.,]\d+)?)\s*m\s*[²2]", text, re.IGNORECASE)
            if m:
                specs["surface_m2"] = self._to_number(m.group(1))

        if "rooms" not in specs:
            m = re.search(r"(\d+)\s+locali", text, re.IGNORECASE)
            if m:
                specs["rooms"] = int(m.group(1))

        if "bathrooms" not in specs:
            m = re.search(r"(\d+)\s+bagni?", text, re.IGNORECASE)
            if m:
                specs["bathrooms"] = int(m.group(1))

        if "floor" not in specs:
            m = re.search(
                r"(\d+\s*[º°]?\s*piano|piano\s+terra|piano\s+rialzato)", text, re.IGNORECASE)
            if m:
                specs["floor"] = m.group(1).strip()

        if "heating" not in specs:
            m = re.search(r"riscaldamento\s+([\w\s]+)", text, re.IGNORECASE)
            if m:
                specs["heating"] = m.group(1).strip()

        return enriched, specs

    def _apply_feature_text(self, text: str, specs: dict, extras: dict) -> None:
        lowered = text.lower()

        if "m²" in lowered or "m2" in lowered:
            val = self._extract_first_number(text)
            if val is not None and "surface_m2" not in specs:
                specs["surface_m2"] = val

        if "locali" in lowered and "rooms" not in specs:
            val = self._extract_first_number(text)
            if val is not None:
                specs["rooms"] = val

        if "bagno" in lowered and "bathrooms" not in specs:
            val = self._extract_first_number(text)
            if val is not None:
                specs["bathrooms"] = val

        if "camera" in lowered and "bedrooms" not in specs:
            val = self._extract_first_number(text)
            if val is not None:
                specs["bedrooms"] = val

        if "piano" in lowered and "floor" not in specs:
            specs["floor"] = text

        if "riscaldamento" in lowered and "heating" not in specs:
            specs["heating"] = text

        if "ascensor" in lowered:
            specs["elevator"] = True
        if "balcone" in lowered or "terraz" in lowered:
            specs["balcony_or_terrace"] = True
        if "garage" in lowered or "box" in lowered or "posto auto" in lowered:
            specs["garage_or_parking"] = True

        if "classe energetica" in lowered:
            extras.setdefault("energy_class_text", text)
            m = re.search(
                r"\((\d+(?:[\.,]\d+)?)\s*kwh", lowered, re.IGNORECASE)
            if m:
                extras.setdefault("energy_kwh_m2_year",
                                  self._to_number(m.group(1)))

        if "costruito nel" in lowered:
            year = self._extract_year(text)
            if year is not None:
                extras.setdefault("year_built", year)

        if "stato" in lowered:
            extras.setdefault("property_state", text)

        if "annuncio aggiornato" in lowered:
            extras.setdefault("updated_relative", text)

    def _extract_address_from_meta(
        self, soup: BeautifulSoup, enriched: dict,
    ) -> None:
        sources: list[str] = []
        for attr, key in [
            ("property", "og:title"),
            ("property", "og:description"),
            ("name", "description"),
        ]:
            tag = soup.find("meta", attrs={attr: key})
            if tag and tag.get("content"):
                sources.append(str(tag["content"]))

        for text in sources:
            match = re.search(
                r"in vendita in\s+(.+?)(?:\s+[—-]\s+idealista|$)",
                text, re.IGNORECASE,
            )
            if match:
                candidate = match.group(1).strip(" ,.-")
                if len(candidate) > 6:
                    enriched["address"] = candidate
                    return

    # ------------------------------------------------------------------ #
    #  Description (full listing text)                                    #
    # ------------------------------------------------------------------ #

    def _extract_description(self, soup: BeautifulSoup, enriched: dict) -> dict:
        selectors = [
            "div.adCommentsLanguage",
            "div.comment",
            "div[class*='description']",
            "article",
            "section[class*='description']",
        ]
        for selector in selectors:
            elem = soup.select_one(selector)
            if elem:
                text = elem.get_text(separator=" ", strip=True)
                if text and len(text) > 100:
                    enriched["summary"] = self._prefer_summary(
                        enriched.get("summary", ""), text,
                    )
                    break
        return enriched

    # ------------------------------------------------------------------ #
    #  Address from DOM selectors                                         #
    # ------------------------------------------------------------------ #

    def _extract_address(self, soup: BeautifulSoup, enriched: dict) -> dict:
        current = str(enriched.get("address", "")).strip()
        selectors = [
            "h1.main-info__title-main",
            "h1[class*='address']",
            "span[itemprop='address']",
            "div[class*='location']",
            "div[class*='address']",
        ]
        for selector in selectors:
            try:
                elem = soup.select_one(selector)
                if elem:
                    text = elem.get_text(strip=True)
                    if text and len(text) > 5:
                        if not current or len(text) > len(current):
                            enriched["address"] = text
                            return enriched
            except Exception:
                continue
        return enriched

    # ------------------------------------------------------------------ #
    #  Helpers                                                            #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _to_int(value) -> Optional[int]:
        if value is None:
            return None
        match = re.search(r"\d+", str(value))
        return int(match.group(0)) if match else None

    @staticmethod
    def _to_number(value) -> Optional[float | int]:
        if value is None:
            return None
        raw = str(value).strip().replace(".", "").replace(",", ".")
        try:
            num = float(raw)
            return int(num) if num.is_integer() else num
        except Exception:
            return None

    @staticmethod
    def _extract_first_number(text: str) -> Optional[int]:
        match = re.search(r"\d+", str(text))
        return int(match.group(0)) if match else None

    @staticmethod
    def _extract_year(text: str) -> Optional[int]:
        match = re.search(r"(19\d{2}|20\d{2})", str(text))
        return int(match.group(1)) if match else None

    @staticmethod
    def _extract_money_int(text: str) -> Optional[int]:
        # Handles formats like "125.000 €" or "1.667 €/m²".
        if not text:
            return None
        match = re.search(r"([\d\.]{2,})(?:\s*€)", str(text))
        if not match:
            return None
        try:
            return int(match.group(1).replace(".", ""))
        except Exception:
            return None

    @staticmethod
    def _prefer_summary(current: str, candidate: str, min_len: int = 80) -> str:
        cur = str(current or "").strip()
        cand = str(candidate or "").strip()
        if not cand or len(cand) < min_len:
            return cur

        def _score(text: str) -> int:
            s = len(text)
            if text.endswith("...") or text.endswith("\u2026"):
                s -= 400
            if len(text) < 120:
                s -= 80
            return s

        return cand if _score(cand) > _score(cur) else cur
