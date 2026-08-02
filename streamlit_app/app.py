import os

import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text


# ============================================================
# Page configuration
# ============================================================

st.set_page_config(
    page_title="SkillBridge Dashboard",
    layout="wide",
)


# ============================================================
# Database connection
# ============================================================

@st.cache_resource
def get_engine():
    """
    Create a PostgreSQL connection engine.

    Streamlit uses this engine to query the gold marts.
    The values come from .env through docker-compose.
    """

    host = os.getenv("POSTGRES_HOST", "postgres")
    port = os.getenv("POSTGRES_PORT", "5432")
    dbname = os.getenv("POSTGRES_DB", "skillbridge_db")
    user = os.getenv("POSTGRES_USER", "skillbridge")
    password = os.getenv("POSTGRES_PASSWORD", "skillbridge")

    database_url = (
        f"postgresql+psycopg://{user}:{password}"
        f"@{host}:{port}/{dbname}"
    )

    return create_engine(database_url)


@st.cache_data(ttl=300)
def load_dataframe(query: str) -> pd.DataFrame:
    """
    Load a SQL query result as a pandas DataFrame.

    ttl=300 means Streamlit caches the result for 5 minutes.
    This avoids querying PostgreSQL again on every small UI change.
    """

    engine = get_engine()

    with engine.connect() as connection:
        return pd.read_sql_query(text(query), connection)


# ============================================================
# Helper functions
# ============================================================

def format_role(role: str) -> str:
    """
    Convert internal role names into readable labels.

    Example:
        data_analyst -> Data Analyst
    """

    if role is None:
        return "Unknown"

    return role.replace("_", " ").title()


def safe_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Replace missing values so the dashboard looks cleaner.
    """

    return df.fillna("")


def deduplicate_skill_names(values) -> list[str]:
    """
    Remove case-only duplicates while preserving a readable display name.

    Examples:
        ["Pandas", "pandas"] -> ["Pandas"]
        ["NumPy", "numpy"]   -> ["NumPy"]
    """

    skills_by_key: dict[str, str] = {}

    for value in values:
        if pd.isna(value):
            continue

        skill_name = str(value).strip()

        if not skill_name:
            continue

        comparison_key = skill_name.casefold()

        if comparison_key not in skills_by_key:
            skills_by_key[comparison_key] = skill_name
            continue

        existing_name = skills_by_key[comparison_key]

        # Prefer a nicely capitalized value over an all-lowercase value.
        if existing_name.islower() and not skill_name.islower():
            skills_by_key[comparison_key] = skill_name

    return sorted(
        skills_by_key.values(),
        key=str.casefold,
    )


# ============================================================
# Load gold marts
# ============================================================

try:
    market_overview = load_dataframe(
        """
        SELECT *
        FROM gold.mart_market_overview
        """
    )

    top_skills_by_role = load_dataframe(
        """
        SELECT *
        FROM gold.mart_top_skills_by_role
        """
    )

    skills_by_category = load_dataframe(
        """
        SELECT *
        FROM gold.mart_skills_by_category
        """
    )

    job_explorer = load_dataframe(
        """
        SELECT *
        FROM gold.mart_job_explorer
        """
    )

except Exception as error:
    st.error("Could not load gold marts from PostgreSQL.")
    st.info(
        "Make sure PostgreSQL is running and dbt has already created the gold tables."
    )
    st.code(
        "docker compose run --rm dbt dbt run --profiles-dir .",
        language="bash",
    )
    st.exception(error)
    st.stop()


# ============================================================
# Sidebar
# ============================================================

st.sidebar.title("SkillBridge")
st.sidebar.caption("Entry-level data job market intelligence")

if st.sidebar.button("Refresh data"):
    st.cache_data.clear()
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.write("Data source: dbt gold marts")


# ============================================================
# App title
# ============================================================

st.title("SkillBridge Dashboard")
st.caption(
    "Analyze entry-level data job postings, demanded skills, and student skill gaps."
)


# ============================================================
# Tabs
# ============================================================

tab_overview, tab_role_skills, tab_categories, tab_jobs, tab_gap = st.tabs(
    [
        "Market Overview",
        "Role Skill Demand",
        "Skill Categories",
        "Job Explorer",
        "Student Skill Gap",
    ]
)


# ============================================================
# Tab 1: Market Overview
# ============================================================

with tab_overview:
    st.header("Market Overview")

    if market_overview.empty:
        st.warning("No market overview data found.")
    else:
        overview = market_overview.iloc[0]

        col1, col2, col3, col4 = st.columns(4)

        col1.metric("Total jobs", int(overview["total_jobs"]))
        col2.metric("Analyzable jobs", int(overview["analyzable_jobs"]))
        col3.metric("Total skills", int(overview["total_skills"]))
        col4.metric("Job-skill links", int(overview["total_job_skill_links"]))

        col5, col6, col7 = st.columns(3)

        col5.metric("Companies", int(overview["total_companies"]))
        col6.metric("Sources", int(overview["total_sources"]))
        col7.metric("Excluded jobs", int(overview["excluded_jobs"]))

    st.subheader("Jobs by detected role")

    non_excluded_jobs = job_explorer[
        job_explorer["is_excluded_from_analysis"] == False
    ].copy()

    if non_excluded_jobs.empty:
        st.info("No analyzable jobs found.")
    else:
        role_counts = (
            non_excluded_jobs.groupby("detected_role")
            .size()
            .reset_index(name="job_count")
            .sort_values("job_count", ascending=False)
        )

        role_counts["role_label"] = role_counts["detected_role"].apply(format_role)

        st.bar_chart(
            role_counts.set_index("role_label")["job_count"]
        )

        st.dataframe(
            role_counts[["role_label", "job_count"]],
            use_container_width=True,
            hide_index=True,
        )


# ============================================================
# Tab 2: Role Skill Demand
# ============================================================

with tab_role_skills:
    st.header("Role Skill Demand")

    if top_skills_by_role.empty:
        st.warning("No skill demand data found.")
    else:
        available_roles = sorted(
            top_skills_by_role["detected_role"].dropna().unique()
        )

        selected_role = st.selectbox(
            "Choose a target role",
            available_roles,
            format_func=format_role,
        )

        col1, col2 = st.columns(2)

        top_n = col1.slider(
            "Number of top skills",
            min_value=5,
            max_value=30,
            value=15,
            step=5,
        )

        min_demand = col2.slider(
            "Minimum demand percentage",
            min_value=0,
            max_value=100,
            value=0,
            step=5,
        )

        role_skill_df = top_skills_by_role[
            (top_skills_by_role["detected_role"] == selected_role)
            & (top_skills_by_role["demand_percentage"] >= min_demand)
        ].copy()

        role_skill_df = role_skill_df.sort_values(
            ["skill_rank", "skill_name"]
        ).head(top_n)

        if role_skill_df.empty:
            st.info("No skills found for this role and filter.")
        else:
            st.subheader(f"Top skills for {format_role(selected_role)}")

            chart_df = role_skill_df.sort_values(
                "demand_percentage", ascending=True
            )

            st.bar_chart(
                chart_df.set_index("skill_name")["demand_percentage"]
            )

            display_df = role_skill_df[
                [
                    "skill_rank",
                    "skill_name",
                    "skill_category",
                    "jobs_with_skill",
                    "total_jobs_for_role",
                    "demand_percentage",
                ]
            ].rename(
                columns={
                    "skill_rank": "Rank",
                    "skill_name": "Skill",
                    "skill_category": "Category",
                    "jobs_with_skill": "Jobs with skill",
                    "total_jobs_for_role": "Total role jobs",
                    "demand_percentage": "Demand %",
                }
            )

            st.dataframe(
                display_df,
                use_container_width=True,
                hide_index=True,
            )

            st.caption(
                "Demand % = jobs for this role mentioning the skill / total analyzable jobs for this role."
            )


# ============================================================
# Tab 3: Skill Categories
# ============================================================

with tab_categories:
    st.header("Skill Categories")

    if skills_by_category.empty:
        st.warning("No skill category data found.")
    else:
        category_df = skills_by_category.sort_values(
            "job_skill_links", ascending=False
        ).copy()

        st.subheader("Category demand")

        st.bar_chart(
            category_df.set_index("skill_category")["job_skill_links"]
        )

        st.dataframe(
            category_df.rename(
                columns={
                    "skill_category": "Category",
                    "distinct_skills_count": "Distinct skills",
                    "jobs_with_category": "Jobs with category",
                    "job_skill_links": "Job-skill links",
                }
            ),
            use_container_width=True,
            hide_index=True,
        )

        st.subheader("Top skills inside a category")

        selected_category = st.selectbox(
            "Choose a category",
            sorted(top_skills_by_role["skill_category"].dropna().unique()),
        )

        category_skills = (
            top_skills_by_role[
                top_skills_by_role["skill_category"] == selected_category
            ]
            .groupby(["skill_name", "skill_category"], as_index=False)
            .agg(
                total_role_skill_mentions=("jobs_with_skill", "sum"),
                avg_demand_percentage=("demand_percentage", "mean"),
            )
            .sort_values("total_role_skill_mentions", ascending=False)
        )

        st.dataframe(
            category_skills.rename(
                columns={
                    "skill_name": "Skill",
                    "skill_category": "Category",
                    "total_role_skill_mentions": "Total role skill mentions",
                    "avg_demand_percentage": "Average demand %",
                }
            ),
            use_container_width=True,
            hide_index=True,
        )


# ============================================================
# Tab 4: Job Explorer
# ============================================================

with tab_jobs:
    st.header("Job Explorer")

    jobs_df = job_explorer.copy()

    show_only_analyzable = st.checkbox(
        "Show only analyzable jobs",
        value=True,
    )

    if show_only_analyzable:
        jobs_df = jobs_df[jobs_df["is_excluded_from_analysis"] == False]

    role_options = sorted(jobs_df["detected_role"].dropna().unique())

    selected_roles = st.multiselect(
        "Filter by role",
        role_options,
        default=role_options,
        format_func=format_role,
    )

    if selected_roles:
        jobs_df = jobs_df[jobs_df["detected_role"].isin(selected_roles)]

    search_text = st.text_input(
        "Search by title, company, location, or skill",
        value="",
    )

    if search_text.strip():
        search = search_text.strip().lower()

        jobs_df = jobs_df[
            jobs_df["job_title"].fillna("").str.lower().str.contains(search)
            | jobs_df["company_name"].fillna("").str.lower().str.contains(search)
            | jobs_df["location_text"].fillna("").str.lower().str.contains(search)
            | jobs_df["skill_names"].fillna("").str.lower().str.contains(search)
        ]

    jobs_df["skill_names"] = jobs_df["skill_names"].fillna("No skills extracted")

    jobs_df["exclusion_status"] = jobs_df[
        "is_excluded_from_analysis"
    ].map(
        {
            True: "Excluded",
            False: "Included",
        }
    )

    display_jobs = jobs_df[
        [
            "job_title",
            "company_name",
            "location_text",
            "detected_role",
            "exclusion_status",
            "skill_names",
            "source_url",
        ]
    ].rename(
        columns={
            "job_title": "Job title",
            "company_name": "Company",
            "location_text": "Location",
            "detected_role": "Detected role",
            "exclusion_status": "Analysis status",
            "skill_names": "Skills",
            "source_url": "Source",
        }
    )

    st.write(f"Showing {len(display_jobs)} jobs")

    st.dataframe(
        safe_dataframe(display_jobs),
        use_container_width=True,
        hide_index=True,
        column_config={
            "Source": st.column_config.LinkColumn("Source"),
        },
    )


# ============================================================
# Tab 5: Student Skill Gap
# ============================================================

with tab_gap:
    st.header("Student Skill Gap")

    st.write(
        "This is a simple comparison between a student's current skills and the top market skills for a selected role."
    )

    if top_skills_by_role.empty:
        st.warning("No skill demand data found.")
    else:
        available_roles = sorted(
            top_skills_by_role["detected_role"].dropna().unique()
        )

        selected_target_role = st.selectbox(
            "Target role",
            available_roles,
            format_func=format_role,
            key="gap_target_role",
        )

        role_top_skills = (
            top_skills_by_role[
                top_skills_by_role["detected_role"] == selected_target_role
            ]
            .sort_values(["skill_rank", "skill_name"])
            .head(15)
            .copy()
        )

        all_skill_options = deduplicate_skill_names(
            top_skills_by_role["skill_name"]
        )

        current_skills = st.multiselect(
            "Select your current skills",
            all_skill_options,
        )

        # Map lowercase comparison keys to readable canonical names.
        required_skill_map = {
            str(skill_name).strip().casefold(): str(skill_name).strip()
            for skill_name in role_top_skills["skill_name"]
            if pd.notna(skill_name)
        }

        current_skill_keys = {
            str(skill_name).strip().casefold()
            for skill_name in current_skills
        }

        matched_skills = sorted(
            [
                display_name
                for comparison_key, display_name in required_skill_map.items()
                if comparison_key in current_skill_keys
            ],
            key=str.casefold,
        )

        missing_skills = sorted(
            [
                display_name
                for comparison_key, display_name in required_skill_map.items()
                if comparison_key not in current_skill_keys
            ],
            key=str.casefold,
        )

        required_skills = set(required_skill_map.values())

        if required_skills:
            coverage = round(
                len(matched_skills) * 100.0 / len(required_skills),
                2,
            )
        else:
            coverage = 0.0

        col1, col2, col3 = st.columns(3)

        col1.metric("Top role skills checked", len(required_skills))
        col2.metric("Skills already covered", len(matched_skills))
        col3.metric("Market skill coverage", f"{coverage}%")

        st.subheader("Skills you already have")

        if matched_skills:
            st.success(", ".join(matched_skills))
        else:
            st.info("No selected skills match the top skills for this role yet.")

        st.subheader("Missing high-demand skills")

        missing_df = role_top_skills[
            role_top_skills["skill_name"].isin(missing_skills)
        ][
            [
                "skill_rank",
                "skill_name",
                "skill_category",
                "demand_percentage",
                "jobs_with_skill",
                "total_jobs_for_role",
            ]
        ].rename(
            columns={
                "skill_rank": "Rank",
                "skill_name": "Missing skill",
                "skill_category": "Category",
                "demand_percentage": "Demand %",
                "jobs_with_skill": "Jobs with skill",
                "total_jobs_for_role": "Total role jobs",
            }
        )

        if missing_df.empty:
            st.success("You cover all top skills for this role.")
        else:
            st.dataframe(
                missing_df,
                use_container_width=True,
                hide_index=True,
            )

        st.caption(
            "This is not a hiring score. It is a simple learning-gap view based on market demand."
        )