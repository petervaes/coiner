import hashlib
import json
from dataclasses import asdict
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st
from streamlit.runtime.uploaded_file_manager import UploadedFile

from coiner.catalog import CatalogIndex
from coiner.models import CatalogEntry, CoinAssessment
from coiner.valuation import (
    PriceEvaluation,
    canonical_grade,
    evaluate_catalog_prices,
    select_nearest_matches,
)
from coiner.vision_inspection import inspect_coin_images
from coiner.vision import VisionError

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CATALOG_DIR = PROJECT_ROOT / "catalog"
DATABASE = PROJECT_ROOT / "data" / "coiner.sqlite3"


@st.cache_resource
def get_catalog() -> CatalogIndex:
    catalog = CatalogIndex(DATABASE)
    catalog.ingest(CATALOG_DIR)
    return catalog


def _upload_key(uploads: list[UploadedFile]) -> str:
    digest = hashlib.sha256()
    for upload in uploads:
        digest.update(upload.name.encode("utf-8"))
        digest.update(upload.getvalue())
    return digest.hexdigest()


def _format_coin(assessment: CoinAssessment) -> str:
    identity = assessment.identity
    year = str(identity.year) if identity.year is not None else "onbekend"
    return f"{identity.country} {identity.denomination} ({year})"


def _matches_dataframe(entries: list[CatalogEntry]) -> pd.DataFrame:
    rows = [
        {
            "Munt": entry.title,
            "Jaar": entry.year,
            "Conditie": entry.condition,
            "Genormaliseerde conditie": canonical_grade(entry.condition) or "—",
            "Catalogusprijs": entry.price,
            "Valuta": entry.currency,
            "Bron": entry.source.title(),
            "Peildatum": entry.as_of,
            "Bronlink": entry.source_url,
        }
        for entry in entries
    ]
    return pd.DataFrame(rows)


def _report_json(
    assessment: CoinAssessment,
    entries: list[CatalogEntry],
    evaluations: list[PriceEvaluation],
) -> bytes:
    report = {
        "report_date": date.today().isoformat(),
        "coin": asdict(assessment.identity),
        "visual_condition": {
            "grade": assessment.condition,
            "notes": assessment.condition_notes,
            "disclaimer": "AI-visuele indicatie; geen professionele certificering.",
        },
        "catalog_price_evaluations": [
            {
                "source": evaluation.source,
                "price": evaluation.price,
                "currency": evaluation.currency,
                "matched_conditions": list(evaluation.matched_conditions),
                "canonical_grade": evaluation.canonical_grade,
                "supporting_catalog_entries": [
                    entry.to_dict() for entry in evaluation.entries
                ],
            }
            for evaluation in evaluations
        ],
        "nearest_catalog_matches": [entry.to_dict() for entry in entries],
        "catalog_disclaimer": (
            "De catalogus bevat vastgelegde bron-snapshots; dit zijn geen live "
            "prijzen of gegarandeerde verkoopopbrengsten."
        ),
    }
    return json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8")


def main() -> None:
    st.set_page_config(page_title="Coiner | Muntanalyse", page_icon="🪙", layout="wide")
    st.title("Coiner — muntinspectie en waardering")
    st.caption(
        "AI-ondersteunde herkenning met bronvermelding. Catalogusprijzen zijn "
        "opgeslagen snapshots, geen live prijsfeed of garantie op verkoopwaarde."
    )

    with st.sidebar:
        st.header("Muntfoto's")
        uploads = st.file_uploader(
            "Sleep één foto of voor- en achterkant hierheen",
            type=["jpg", "jpeg", "png", "webp", "gif"],
            accept_multiple_files=True,
            key="coin_photos",
        )
        if len(uploads) > 2:
            st.error("Upload maximaal twee foto's.")
        elif uploads:
            st.caption(
                "Eerste foto: voorkant. Tweede foto (indien aanwezig): achterkant."
            )
        analyze = st.button(
            "Inspecteer munt",
            type="primary",
            disabled=not uploads or len(uploads) > 2,
            use_container_width=True,
        )

    current_key = _upload_key(uploads) if uploads and len(uploads) <= 2 else None
    if analyze and current_key is not None:
        image_data = [(upload.type, upload.getvalue()) for upload in uploads]
        try:
            with st.spinner("Foto('s) worden door GPT-Vision onderzocht..."):
                assessment = inspect_coin_images(image_data)
            identity = assessment.identity
            matches = get_catalog().search(
                identity.search_text(),
                limit=100,
                country=identity.country,
                denomination=identity.denomination,
                year=identity.year,
            )
            candidates = matches
            matches = select_nearest_matches(candidates, assessment.condition)
            evaluation = evaluate_catalog_prices(candidates, assessment.condition)
            st.session_state["coin_result"] = {
                "key": current_key,
                "assessment": assessment,
                "matches": matches,
                "candidates": candidates,
                "evaluation": evaluation,
            }
        except (VisionError, FileNotFoundError, ValueError) as exc:
            st.error(f"Inspectie mislukt: {exc}")

    result = st.session_state.get("coin_result")
    if not uploads:
        st.info("Upload één of twee foto's om te beginnen.")
        return
    if not current_key or not result or result["key"] != current_key:
        st.info("Upload compleet. Klik op **Inspecteer munt** om de analyse te starten.")
        if uploads:
            previews = st.columns(min(len(uploads), 2))
            for index, (column, upload) in enumerate(zip(previews, uploads)):
                with column:
                    st.image(
                        upload.getvalue(),
                        caption="Voorkant" if index == 0 else "Achterkant",
                        use_container_width=True,
                    )
        return

    assessment = result["assessment"]
    matches = result["matches"]
    evaluations = result["evaluation"]
    left, right = st.columns([1, 1])
    with left:
        st.subheader("Muntfoto")
        previews = st.columns(min(len(uploads), 2))
        for index, (column, upload) in enumerate(zip(previews, uploads)):
            with column:
                st.image(
                    upload.getvalue(),
                    caption="Voorkant" if index == 0 else "Achterkant",
                    use_container_width=True,
                )
    with right:
        st.subheader("GPT-Vision inspectie")
        st.write(f"**Munt:** {_format_coin(assessment)}")
        st.write(f"**Conditie (visuele indicatie):** {assessment.condition}")
        if assessment.identity.mint:
            st.write(f"**Muntplaats:** {assessment.identity.mint}")
        if assessment.identity.ruler_or_issuer:
            st.write(f"**Uitgever:** {assessment.identity.ruler_or_issuer}")
        if assessment.condition_notes:
            st.info(assessment.condition_notes)
        st.caption("Conditie is een AI-inschatting, geen professionele grading.")

    st.subheader("Dichtstbijzijnde catalogusmatches")
    if matches:
        st.dataframe(
            _matches_dataframe(matches),
            hide_index=True,
            use_container_width=True,
            column_config={
                "Bronlink": st.column_config.LinkColumn("Bronlink"),
                "Catalogusprijs": st.column_config.NumberColumn(
                    "Catalogusprijs", format="%.2f"
                ),
            },
        )
    else:
        st.warning(
            "Geen catalogusmatches voor deze munt; er wordt geen prijs afgeleid."
        )

    st.subheader("Cataloguswaarderingen per bron")
    if evaluations:
        source_columns = st.columns(len(evaluations))
        for column, evaluation in zip(source_columns, evaluations):
            with column:
                st.metric(
                    f"{evaluation.source.title()} ({evaluation.currency})",
                    f"{evaluation.price:.2f} {evaluation.currency}",
                )
                st.caption(
                    "Conditie "
                    f"{', '.join(evaluation.matched_conditions)} gematcht als "
                    f"{evaluation.canonical_grade}; catalogus-snapshot, geen "
                    "live marktprijs."
                )
    else:
        st.warning(
            "Geen prijs gevonden met een bekende equivalente conditie. "
            "De conditielabels zijn niet automatisch gematcht."
        )
    st.caption(
        "Numista en LeFranc worden apart getoond; hun prijzen worden niet "
        "gemiddeld of tussen valuta omgerekend."
    )
    st.download_button(
        "Download taxatierapport (JSON)",
        data=_report_json(assessment, matches, evaluations),
        file_name="coiner-taxatierapport.json",
        mime="application/json",
    )


if __name__ == "__main__":
    main()
