"""Immobiliare.it listing enrichment handler.

Extracts structured data from Immobiliare.it pages using:
- OpenGraph / meta tags
- Main overview cards
- Feature grids (dt/dd)
- Price/cost/energy sections
"""

import re
from typing import Optional
from urllib.parse import urlparse, urlunparse

from bs4 import BeautifulSoup

from worker.sites.base import BaseSiteHandler


class ImmobiliareSiteHandler(BaseSiteHandler):
    @property
    def site_name(self) -> str:
        return "immobiliare"

    def can_handle(self, url: str) -> bool:
        lowered = str(url or "").lower()
        return "immobiliare.it" in lowered and "/annunci/" in lowered

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

    def enrich(self, soup: BeautifulSoup, payload: dict) -> dict:
        enriched = dict(payload)
        enriched["source_site"] = self.site_name
        specs = dict(enriched.get("specs") or {})
        extras = dict(enriched.get("extras") or {})

        enriched = self._extract_meta(soup, enriched)
        enriched, specs, extras = self._extract_overview(
            soup, enriched, specs, extras)
        enriched, specs, extras = self._extract_feature_grids(
            soup, enriched, specs, extras)
        enriched, extras = self._extract_price_and_costs(
            soup, enriched, extras)
        enriched, extras = self._extract_energy_block(soup, enriched, extras)
        enriched, extras = self._extract_reference_and_people(
            soup, enriched, extras)
        enriched, extras = self._extract_structured_characteristics(
            soup, enriched, extras)
        enriched, extras = self._extract_surface_details(soup, enriched, extras)
        enriched, extras = self._extract_additional_features(soup, enriched, extras)
        enriched, extras = self._extract_listing_context(soup, enriched, extras)
        enriched = self._extract_description(soup, enriched)

        if specs:
            enriched["specs"] = specs
        if extras:
            enriched["extras"] = extras
        return enriched

    def _extract_meta(self, soup: BeautifulSoup, enriched: dict) -> dict:
        og_title = soup.find("meta", attrs={"property": "og:title"})
        if og_title and og_title.get("content") and not enriched.get("title"):
            enriched["title"] = str(og_title.get("content")).strip()

        og_desc = soup.find("meta", attrs={"property": "og:description"})
        if og_desc and og_desc.get("content"):
            enriched["summary"] = self._prefer_summary(
                enriched.get("summary", ""),
                str(og_desc.get("content")).strip(),
            )

        meta_desc = soup.find("meta", attrs={"name": "description"})
        if meta_desc and meta_desc.get("content"):
            enriched["summary"] = self._prefer_summary(
                enriched.get("summary", ""),
                str(meta_desc.get("content")).strip(),
            )

        og_image = soup.find("meta", attrs={"property": "og:image"})
        if og_image and og_image.get("content") and not enriched.get("image"):
            enriched["image"] = str(og_image.get("content")).strip()

        og_url = soup.find("meta", attrs={"property": "og:url"})
        if og_url and og_url.get("content"):
            normalized = self.normalize_url(str(og_url.get("content")).strip())
            enriched["url"] = normalized
            match = re.search(r"/annunci/(\d+)", normalized)
            if match:
                enriched.setdefault("extras", {})
                enriched["extras"]["listing_id"] = match.group(1)

        if not enriched.get("price"):
            for candidate in [
                str(og_title.get("content") or "") if og_title else "",
                str(og_desc.get("content") or "") if og_desc else "",
                str(meta_desc.get("content") or "") if meta_desc else "",
            ]:
                value = self._extract_money_int(candidate)
                if value is not None:
                    enriched["price"] = value
                    break

        return enriched

    def _extract_overview(
        self,
        soup: BeautifulSoup,
        enriched: dict,
        specs: dict,
        extras: dict,
    ) -> tuple[dict, dict, dict]:
        title_h1 = soup.select_one("h1[class*='Title_title']")
        if title_h1:
            text = title_h1.get_text(" ", strip=True)
            if text:
                enriched["title"] = text

        if not enriched.get("price"):
            price_node = soup.select_one("div[class*='Price_price'] span") or soup.select_one(
                "div[class*='Price_price']"
            )
            if price_node:
                value = self._extract_money_int(
                    price_node.get_text(" ", strip=True))
                if value is not None:
                    enriched["price"] = value

        location_parts = [
            span.get_text(" ", strip=True)
            for span in soup.select("button[class*='BlockTitle_link'] span[class*='LocationInfo_location']")
            if span.get_text(" ", strip=True)
        ]
        if location_parts:
            enriched["address"] = ", ".join(location_parts)
            extras.setdefault("city", location_parts[0])
            if len(location_parts) > 1:
                extras.setdefault("street", location_parts[1])
            if len(location_parts) > 2:
                extras.setdefault("area", ", ".join(location_parts[2:]))

        # Top badges like "2 locali", "56 m²", "1 bagno", "No Ascensore", "Balcone".
        for item in soup.select("div[class*='MainFeatures_item'] span[class*='MainFeatures_text']"):
            self._apply_feature_text(item.get_text(
                " ", strip=True), specs, extras)

        return enriched, specs, extras

    def _extract_feature_grids(
        self,
        soup: BeautifulSoup,
        enriched: dict,
        specs: dict,
        extras: dict,
    ) -> tuple[dict, dict, dict]:
        for row in soup.select("dl[class*='FeaturesGrid_list'] div[class*='Item_item']"):
            dt = row.select_one("dt")
            dd = row.select_one("dd")
            if not dt or not dd:
                continue
            key = dt.get_text(" ", strip=True).lower()
            value = dd.get_text(" ", strip=True)
            if not key or not value:
                continue

            if "piano" in key and "floor" not in specs:
                specs["floor"] = value
            elif "superficie" in key and "surface_m2" not in specs:
                number = self._extract_number(value)
                if number is not None:
                    specs["surface_m2"] = number
            elif "locali" in key and "rooms" not in specs:
                number = self._extract_int(value)
                if number is not None:
                    specs["rooms"] = number
            elif "camere da letto" in key and "bedrooms" not in specs:
                number = self._extract_int(value)
                if number is not None:
                    specs["bedrooms"] = number
            elif "bagni" in key and "bathrooms" not in specs:
                number = self._extract_int(value)
                if number is not None:
                    specs["bathrooms"] = number
            elif "ascensore" in key:
                specs["elevator"] = value.strip().lower() not in {
                    "no", "assente"}
            elif "balcone" in key:
                specs["balcony_or_terrace"] = value.strip(
                ).lower().startswith("s")
            elif "terrazzo" in key and not specs.get("balcony_or_terrace"):
                specs["balcony_or_terrace"] = value.strip(
                ).lower().startswith("s")
            elif "box" in key or "posti auto" in key:
                specs["garage_or_parking"] = value.strip().lower() not in {
                    "no", "nessuno"}
                extras["parking_details"] = value
            elif "riscaldamento" in key and "heating" not in specs:
                specs["heating"] = value
            elif "tipologia" in key:
                extras["property_type"] = value
            elif "contratto" in key:
                extras["contract"] = value
            elif "cucina" in key:
                extras["kitchen"] = value
            elif "arredato" in key:
                extras["furnished"] = value
            elif "climatizzazione" in key:
                extras["climatization"] = value

        return enriched, specs, extras

    def _extract_price_and_costs(
        self,
        soup: BeautifulSoup,
        enriched: dict,
        extras: dict,
    ) -> tuple[dict, dict]:
        for row in soup.select("div[class*='ListingDetail_divider'] dl[class*='FeaturesGrid_list'] div[class*='Item_item']"):
            dt = row.select_one("dt")
            dd = row.select_one("dd")
            if not dt or not dd:
                continue
            key = dt.get_text(" ", strip=True).lower()
            value = dd.get_text(" ", strip=True)

            if "prezzo" in key and "prezzo al m" not in key and not enriched.get("price"):
                money = self._extract_money_int(value)
                if money is not None:
                    enriched["price"] = money
            elif "prezzo al m" in key:
                money = self._extract_money_int(value)
                if money is not None:
                    extras["price_per_m2"] = money
                    enriched.setdefault("pricing", {})["price_per_m2"] = money
            elif "spese condominio" in key:
                extras["condo_fees"] = value
                monthly = self._extract_money_int(value)
                if monthly is not None:
                    extras["condo_fees_monthly_eur"] = monthly
                    enriched.setdefault("pricing", {})["condo_fees_monthly_eur"] = monthly

        if enriched.get("price") is not None:
            enriched.setdefault("pricing", {})["price"] = enriched.get("price")
        if extras.get("condo_fees"):
            enriched.setdefault("pricing", {})["condo_fees"] = extras.get("condo_fees")

        return enriched, extras

    def _extract_energy_block(
        self,
        soup: BeautifulSoup,
        enriched: dict,
        extras: dict,
    ) -> tuple[dict, dict]:
        for li in soup.select("ul[class*='Energy_wrapper'] li"):
            label = li.select_one("p")
            value = li.select_one("span")
            if not label or not value:
                continue
            key = label.get_text(" ", strip=True).lower()
            val = value.get_text(" ", strip=True)
            if not key or not val:
                continue

            if "anno di costruzione" in key:
                year = self._extract_int(val)
                if year is not None:
                    extras["year_built"] = year
                    enriched.setdefault("energy", {})["year_built"] = year
            elif key == "stato":
                extras["property_state"] = val
                enriched.setdefault("energy", {})["property_state"] = val
            elif "riscaldamento" in key:
                enriched.setdefault("specs", {})
                if not enriched["specs"].get("heating"):
                    enriched["specs"]["heating"] = val
                enriched.setdefault("energy", {})["heating"] = val
            elif "climatizz" in key:
                extras["climatization"] = val
                enriched.setdefault("energy", {})["climatization"] = val

        return enriched, extras

    def _extract_reference_and_people(
        self,
        soup: BeautifulSoup,
        enriched: dict,
        extras: dict,
    ) -> tuple[dict, dict]:
        # Last update text.
        update_block = soup.select_one("div[class*='LastUpdate_wrapper']")
        if update_block:
            extras["updated_text"] = update_block.get_text(" ", strip=True)

        # Listing reference.
        ref_node = soup.select_one("p[class*='Heading_reference']")
        if ref_node:
            ref_text = ref_node.get_text(" ", strip=True)
            extras["reference"] = ref_text
            ref_val = re.search(r"riferimento\s*:?\s*(\S+)",
                                ref_text, re.IGNORECASE)
            if ref_val:
                extras["reference_id"] = ref_val.group(1)

        # Agent / agency labels.
        manager = soup.select_one("p[class*='Manager_text']")
        if manager:
            extras["agent_name"] = manager.get_text(" ", strip=True)
            enriched.setdefault("contact", {})["agent_name"] = extras["agent_name"]

        agency = soup.select_one("div[class*='Referent_referent'] p")
        if agency:
            extras["agency_name"] = agency.get_text(" ", strip=True)
            enriched.setdefault("contact", {})["agency_name"] = extras["agency_name"]

        if extras.get("reference_id"):
            enriched.setdefault("contact", {})["reference_id"] = extras["reference_id"]
        if extras.get("updated_text"):
            enriched.setdefault("contact", {})["updated_text"] = extras["updated_text"]

        return enriched, extras

    def _extract_structured_characteristics(
        self,
        soup: BeautifulSoup,
        enriched: dict,
        extras: dict,
    ) -> tuple[dict, dict]:
        characteristics: dict[str, str] = {}

        anchor = soup.select_one("span[id='caratteristiche']")
        if anchor:
            block = anchor.find_parent("div")
            if block:
                listing_divider = block.find_parent("div")
                if listing_divider:
                    rows = listing_divider.select(
                        "dl[class*='FeaturesGrid_list'] div[class*='Item_item']"
                    )
                    for row in rows:
                        dt = row.select_one("dt")
                        dd = row.select_one("dd")
                        if not dt or not dd:
                            continue
                        key = dt.get_text(" ", strip=True)
                        value = dd.get_text(" ", strip=True)
                        if key and value:
                            characteristics[key] = value

        if characteristics:
            enriched["characteristics"] = characteristics
            extras["characteristics_count"] = len(characteristics)

        return enriched, extras

    def _extract_surface_details(
        self,
        soup: BeautifulSoup,
        enriched: dict,
        extras: dict,
    ) -> tuple[dict, dict]:
        surfaces: list[dict] = []
        for block in soup.select("div[class*='SurfaceElement_element']"):
            title_node = block.select_one("p[class*='SurfaceElement_title']")
            details = {
                "name": title_node.get_text(" ", strip=True) if title_node else None,
            }

            dts = block.select("dl dt")
            dds = block.select("dl dd")
            for dt, dd in zip(dts, dds):
                key = dt.get_text(" ", strip=True).lower()
                value = dd.get_text(" ", strip=True)
                if not key or not value:
                    continue
                if key == "piano":
                    details["floor"] = value
                elif key == "superficie":
                    details["surface_m2"] = self._extract_number(value)
                elif key == "coefficiente":
                    details["coefficient_pct"] = self._extract_int(value)
                elif key == "tipo superficie":
                    details["surface_type"] = value
                elif "sup. commerciale" in key:
                    details["commercial_surface_m2"] = self._extract_number(value)

            if details.get("name"):
                surfaces.append(details)

        if surfaces:
            enriched["surfaces"] = surfaces
            extras["surface_breakdown_count"] = len(surfaces)
            total_commercial = sum(
                float(item.get("commercial_surface_m2"))
                for item in surfaces
                if isinstance(item.get("commercial_surface_m2"), (int, float))
            )
            if total_commercial > 0:
                extras["surface_commercial_total_m2"] = total_commercial
        return enriched, extras

    def _extract_additional_features(
        self,
        soup: BeautifulSoup,
        enriched: dict,
        extras: dict,
    ) -> tuple[dict, dict]:
        badges = [
            node.get_text(" ", strip=True)
            for node in soup.select("div[class*='FeaturesBadges_badges'] li span")
            if node.get_text(" ", strip=True)
        ]
        if badges:
            enriched["additional_features"] = badges
            extras["additional_features_count"] = len(badges)
        return enriched, extras

    def _extract_listing_context(
        self,
        soup: BeautifulSoup,
        enriched: dict,
        extras: dict,
    ) -> tuple[dict, dict]:
        listing = dict(enriched.get("listing") or {})

        nav_count = soup.select_one("span[class*='ListingsNav_count']")
        if nav_count:
            text = nav_count.get_text(" ", strip=True)
            listing["nav_position"] = text
            m = re.search(r"(\d+)\s+di\s+(\d+)", text.lower())
            if m:
                listing["position"] = int(m.group(1))
                listing["total_results"] = int(m.group(2))

        motive = soup.select_one("div[class*='nd-select__value']")
        if motive:
            listing["contact_reason_default"] = motive.get_text(" ", strip=True)

        if listing:
            enriched["listing"] = listing

        return enriched, extras

    def _extract_description(self, soup: BeautifulSoup, enriched: dict) -> dict:
        # Prefer the long description in the dedicated block.
        for selector in [
            "div[class*='ReadAll_readAll'] > div",
            "div[class*='ReadAll_readAll']",
            "section[id='descrizione']",
        ]:
            node = soup.select_one(selector)
            if not node:
                continue
            text = node.get_text(" ", strip=True)
            if text and len(text) > 80:
                enriched["summary"] = self._prefer_summary(
                    enriched.get("summary", ""),
                    text,
                    min_len=80,
                )
                break
        return enriched

    def _apply_feature_text(self, text: str, specs: dict, extras: dict) -> None:
        lowered = text.lower()
        if not lowered:
            return

        if "locali" in lowered and "rooms" not in specs:
            value = self._extract_int(text)
            if value is not None:
                specs["rooms"] = value

        if ("m²" in lowered or "m2" in lowered) and "surface_m2" not in specs:
            value = self._extract_number(text)
            if value is not None:
                specs["surface_m2"] = value

        if "bagno" in lowered and "bathrooms" not in specs:
            value = self._extract_int(text)
            if value is not None:
                specs["bathrooms"] = value

        if "piano" in lowered and "floor" not in specs:
            specs["floor"] = text

        if "no ascensore" in lowered:
            specs["elevator"] = False
        elif "ascensore" in lowered:
            specs["elevator"] = True

        if "balcone" in lowered or "terrazzo" in lowered:
            specs["balcony_or_terrace"] = True

        if "parzialmente arredato" in lowered:
            extras.setdefault("furnished", text)

    @staticmethod
    def _extract_money_int(text: str) -> Optional[int]:
        if not text:
            return None
        match = re.search(r"€\s*([\d\.\s,]{2,})", str(text))
        if not match:
            match = re.search(r"([\d\.\s,]{2,})\s*€", str(text))
        if not match:
            return None
        try:
            raw = match.group(1).replace(".", "").replace(" ", "")
            if "," in raw:
                raw = raw.split(",", 1)[0]
            return int(raw)
        except Exception:
            return None

    @staticmethod
    def _extract_int(text: str) -> Optional[int]:
        match = re.search(r"\d+", str(text or ""))
        return int(match.group(0)) if match else None

    @staticmethod
    def _extract_number(text: str) -> Optional[float | int]:
        match = re.search(r"(\d+(?:[\.,]\d+)?)", str(text or ""))
        if not match:
            return None
        raw = match.group(1).replace(".", "").replace(",", ".")
        try:
            num = float(raw)
            return int(num) if num.is_integer() else num
        except Exception:
            return None

    @staticmethod
    def _prefer_summary(current: str, candidate: str, min_len: int = 80) -> str:
        cur = str(current or "").strip()
        cand = str(candidate or "").strip()
        if not cand or len(cand) < min_len:
            return cur

        def _score(text: str) -> int:
            score = len(text)
            if text.endswith("...") or text.endswith("\u2026"):
                score -= 300
            return score

        return cand if _score(cand) > _score(cur) else cur
