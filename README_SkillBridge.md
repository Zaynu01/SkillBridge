# SkillBridge: Job Market Intelligence and Skill Gap Recommendation Platform

## 1. Project Overview

**SkillBridge** is a production-inspired data engineering and NLP prototype that analyzes job postings and helps students understand which data-related roles match their current skills and what skills they should learn next.

The platform collects job postings through a controlled scraping pipeline, stores the raw data, cleans and enriches the job descriptions, extracts and standardizes required skills, detects seniority level using rules, transforms the data with dbt, and displays insights through a Streamlit dashboard.

Students can manually enter their current skills, and the system compares those skills with real market skill profiles built from job postings. Based on that comparison, the platform shows:

```text
Which data-related roles the student is closest to
What skills the student already has
What important skills the student is missing
What the student should learn next
```

The goal is **not** to predict the job title, because job postings usually already mention the role.

The real goal is to answer:

> “Based on real job market data, what skills should a student learn to become ready for a specific data-related role?”

---

## 2. Problem the Project Solves

Many students want to work as:

```text
Data Analyst
BI Analyst
Data Engineer
Machine Learning Engineer
Data Scientist
```

But they are often confused about what to learn first.

For example, a student may ask:

```text
Should I learn Power BI or Tableau?
Is SQL more important than Python?
Do Data Engineer internships require Spark?
Should I learn Docker and Airflow?
Am I closer to Data Analyst or Data Engineer?
What skills am I missing?
```

A student can read one job post and understand it.

But a student cannot easily analyze hundreds or thousands of job postings and know:

```text
Which skills appear most often
Which skills are required for each role
Which skills are common for entry-level roles
Which skills are more common in senior roles
Which roles match their current skills
Which skills they should prioritize next
```

This project solves that problem by turning job postings into clear, data-driven career guidance.

---

## 3. Main Users

The platform is mainly useful for three types of users.

### Students

Students use it to know:

```text
Which data-related role fits their current skills
What skills they are missing
What learning path they should follow
```

### Universities

Universities can use it to understand:

```text
What skills companies are currently asking for
Whether students are learning market-relevant skills
Which skills should be emphasized in training programs
```

### Career Centers

Career centers can use it to guide students using real job market data instead of general advice.

---

## 4. Final Project Flow

The final project flow is:

```text
1. Scrape job postings
        ↓
2. Save raw scraped data
        ↓
3. Clean and preprocess the data
        ↓
4. Extract and normalize skills
        ↓
5. Detect seniority level
        ↓
6. Load enriched data into PostgreSQL
        ↓
7. Transform data with dbt
        ↓
8. Build market skill profiles
        ↓
9. Student enters current skills
        ↓
10. Calculate role match scores
        ↓
11. Recommend missing skills
        ↓
12. Display everything in a Streamlit dashboard
```

---

## 5. Step-by-Step Explanation

### Step 1: Scrape Job Postings

The project collects job postings from one or two selected sources using a controlled scraping pipeline.

Each scraped job posting should contain:

```text
job_title
company
location
description
posting_date
source_url
source_name
```

Example:

```text
Title: Junior Data Engineer
Company: ExampleTech
Location: Casablanca
Description: We are looking for someone with Python, SQL, PostgreSQL, Docker, and Airflow.
```

The scraping should be **batch scraping**, not live scraping every time the dashboard runs.

The scraper runs, collects jobs, and saves them into raw files.

Example:

```text
Run scraper
↓
Save results to raw JSON/CSV
↓
Run the pipeline using saved data
```

This keeps the project stable during demos, even if the website changes or blocks scraping later.

---

### Step 2: Save Raw Scraped Data

The original scraped data is saved before any cleaning or transformation.

Example:

```text
data/raw/jobs_2026_06_18.json
```

This is important because a proper data engineering pipeline should preserve raw data.

If cleaning logic changes later, the raw data can be reprocessed.

---

### Step 3: Clean and Preprocess the Data

Raw job data is usually messy.

The cleaning step handles:

```text
Removing HTML tags
Removing duplicated jobs
Removing empty descriptions
Standardizing dates
Standardizing locations
Cleaning extra spaces
Preparing text for processing
```

Example before cleaning:

```text
<p>We are looking for <b>Data Engineer</b> &amp; Python developer...</p>
```

Example after cleaning:

```text
We are looking for Data Engineer and Python developer...
```

The output is a clean job postings dataset ready for enrichment.

---

### Step 4: Extract and Normalize Skills

This is the main NLP component of the project.

The system reads job descriptions and extracts required skills.

Example:

```text
Input description:
We need experience with Python, PostgreSQL, Apache Airflow, and PowerBI.

Extracted skills:
Python
PostgreSQL
Airflow
Power BI
```

After extraction, the system normalizes skill names.

Example:

```text
Postgres → PostgreSQL
PowerBI → Power BI
Apache Airflow → Airflow
Apache Spark → Spark
```

For the two-month version, this can be done using:

```text
Skill dictionary
Regex
Synonym mapping
```

This is not a heavy deep learning model. It is an NLP-based data enrichment component that makes unstructured job descriptions usable for analysis.

---

### Step 5: Detect Seniority Level

Seniority detection should be rule-based.

The system checks the job title and description to classify the job into one of these categories:

```text
Internship
Junior
Intermediate
Senior
Unknown
```

Example rules:

```text
intern, internship, stagiaire, stage, trainee → Internship
junior, entry-level, débutant, 0-2 years → Junior
3-5 years, confirmed, intermediate → Intermediate
senior, lead, expert, manager, architect, 5+ years → Senior
no clear evidence → Unknown
```

Example:

```text
Title: Data Analyst
Description: Strong SQL and Power BI skills required.

Output:
Seniority: Unknown
```

The `Unknown` category is important because the system should not guess when there is not enough evidence.

---

### Step 6: Load Enriched Data into PostgreSQL

After cleaning, skill extraction, skill normalization, and seniority detection, the enriched data is loaded into PostgreSQL.

Main tables can include:

### `job_postings`

Stores job information.

```text
job_id
title
company
location
description
posting_date
source
source_url
```

### `skills`

Stores the list of standardized skills.

```text
skill_id
skill_name
skill_category
```

### `job_skills`

Stores which skills appear in each job.

```text
job_id
skill_id
```

### `job_analysis`

Stores extracted information about each job.

```text
job_id
role
seniority_level
junior_friendly
```

At this stage, the project has clean and structured data stored in a real database.

---

### Step 7: Transform Data with dbt

dbt is used to show the data engineering transformation process.

The project follows an ELT-style flow:

```text
Extract → Load → Transform
```

Meaning:

```text
Scrape data
↓
Save raw files
↓
Load data into PostgreSQL
↓
Use dbt to transform the data into analytics-ready tables
```

dbt should not be used for scraping or Python cleaning.

dbt should be used for SQL transformations such as staging, intermediate models, and marts.

Example dbt models:

```text
stg_job_postings
stg_job_skills
stg_job_analysis
int_skill_counts_by_role
int_skill_counts_by_seniority
mart_role_skill_profiles
mart_top_skills_by_role
mart_seniority_distribution
mart_job_market_overview
```

This clearly shows the data engineering process:

```text
Raw database tables
        ↓
dbt staging models
        ↓
dbt intermediate models
        ↓
dbt marts
        ↓
Dashboard-ready tables
```

---

### Step 8: Build Market Skill Profiles

Using dbt, the system calculates skill demand for each role.

Example Data Analyst profile:

| Skill | Demand |
|---|---:|
| SQL | 85% |
| Excel | 78% |
| Power BI | 65% |
| Python | 55% |
| Statistics | 42% |

Example Data Engineer profile:

| Skill | Demand |
|---|---:|
| SQL | 88% |
| Python | 80% |
| PostgreSQL | 58% |
| Docker | 50% |
| Airflow | 46% |
| Spark | 38% |

This allows the platform to say:

```text
For Data Engineer roles, the most important skills are SQL, Python, PostgreSQL, Docker, Airflow, and Spark.
```

These market skill profiles are the foundation for the recommendation system.

---

### Step 9: Student Enters Current Skills

In the Streamlit dashboard, the student manually selects or enters their current skills.

Example:

```text
Python
SQL
Excel
Power BI
```

No CV upload is needed in the first version.

Manual skill input keeps the project simple, clear, and feasible within two months.

---

### Step 10: Calculate Role Match Scores

The system compares the student's skills with the market skill profile for each role.

Example student skills:

```text
Python, SQL, Excel, Power BI
```

The system compares them with:

```text
Data Analyst profile
BI Analyst profile
Data Engineer profile
ML Engineer profile
```

Example result:

| Role | Match Score |
|---|---:|
| Data Analyst | 82% |
| BI Analyst | 76% |
| Data Engineer | 45% |
| ML Engineer | 38% |

A simple match score formula can be:

```text
Match score = importance of skills the student has / total importance of required skills for that role
```

Example:

```text
Data Engineer important skills:
SQL = 88
Python = 80
PostgreSQL = 58
Docker = 50
Airflow = 46
Spark = 38

Student has:
SQL + Python

Score:
(88 + 80) / (88 + 80 + 58 + 50 + 46 + 38)
```

This part is a recommendation/scoring algorithm. It does not need to be a complex ML model.

---

### Step 11: Recommend Missing Skills

The platform finds the important skills that the student does not have.

Example:

```text
Target role: Data Engineer

Student has:
Python, SQL

Market profile requires:
SQL
Python
PostgreSQL
Docker
Airflow
Spark
dbt

Missing skills:
PostgreSQL
Docker
Airflow
Spark
dbt
```

The missing skills are ranked based on market demand.

So the system recommends the most demanded missing skills first.

Example recommendation:

```text
1. PostgreSQL
2. Docker
3. Airflow
4. Spark
5. dbt
```

---

### Step 12: Display Everything in Streamlit

The Streamlit dashboard is the main user interface.

It should contain four main pages.

### Page 1: Market Overview

Shows:

```text
Total jobs collected
Top roles
Top skills
Top locations
Seniority distribution
Unknown seniority percentage
```

### Page 2: Role Analysis

The user selects a role.

The dashboard shows:

```text
Top skills for that role
Skill demand percentage
Junior vs senior distribution
Common skill combinations
```

### Page 3: Student Skill Gap

The student selects their skills.

The dashboard shows:

```text
Closest roles
Match scores
Skills already known
Missing skills
Recommended learning order
```

### Page 4: Job Explorer

Shows:

```text
Job title
Company
Location
Extracted skills
Seniority level
Source URL
```

---

## 6. Where the NLP/ML Component Is

This project should not be presented as a heavy machine learning project.

It should be presented as:

> A data engineering project with an NLP-based skill extraction and recommendation component.

The NLP/ML-related part is here:

```text
Job descriptions
        ↓
NLP skill extraction
        ↓
Skill normalization
        ↓
Skill profiles
        ↓
Student-role matching
        ↓
Skill recommendations
```

More specifically:

| Component | ML/NLP or Not? | Explanation |
|---|---|---|
| Scraping | No | Data collection |
| Raw storage | No | Data engineering |
| Cleaning | No | Data preprocessing |
| Skill extraction | Yes, NLP-lite | Extract skills from unstructured job descriptions using dictionary, regex, and synonyms |
| Skill normalization | Yes, NLP-lite | Map different names to one standard skill |
| Seniority detection | Rule-based NLP | Detect seniority using keywords and years of experience |
| PostgreSQL | No | Data storage |
| dbt | No | SQL transformation and analytics modeling |
| Market skill profiles | No | Analytics/statistics |
| Student match score | Recommendation logic | Compares student skills to market profiles |
| Missing skill recommendation | Recommendation logic | Ranks missing skills by market demand |
| Streamlit | No | UI/dashboard |

---

## 7. Technical Architecture

The project runs inside Docker Compose.

```text
                          Docker Compose
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│  ┌──────────────┐        ┌──────────────────────────────┐   │
│  │ Job Websites │        │ Python Scraper / Pipeline     │   │
│  └──────┬───────┘        │ - scrape jobs                 │   │
│         │                │ - save raw data               │   │
│         ↓                │ - clean text                  │   │
│  ┌──────────────┐        │ - extract skills              │   │
│  │ Raw JSON/CSV │        │ - normalize skills            │   │
│  └──────┬───────┘        │ - detect seniority            │   │
│         │                └──────────────┬───────────────┘   │
│         ↓                               ↓                   │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ PostgreSQL                                           │   │
│  │ - job_postings                                       │   │
│  │ - skills                                             │   │
│  │ - job_skills                                         │   │
│  │ - job_analysis                                       │   │
│  └──────────────────────┬───────────────────────────────┘   │
│                         ↓                                   │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ dbt                                                  │   │
│  │ - staging models                                     │   │
│  │ - intermediate models                                │   │
│  │ - mart tables                                        │   │
│  └──────────────────────┬───────────────────────────────┘   │
│                         ↓                                   │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ Streamlit Dashboard                                  │   │
│  │ - market overview                                    │   │
│  │ - role analysis                                      │   │
│  │ - student skill gap                                  │   │
│  │ - job explorer                                       │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 8. Suggested Tech Stack

| Layer | Tool |
|---|---|
| Scraping | Python, requests, BeautifulSoup, Playwright if needed |
| Raw storage | JSON/CSV files |
| Data cleaning | Python, pandas, regex |
| NLP-lite skill extraction | Skill dictionary, regex, synonym mapping |
| Database | PostgreSQL |
| Transformations | dbt |
| Dashboard | Streamlit |
| Containerization | Docker, Docker Compose |
| Version control | Git, GitHub |

---

## 9. Recommended Docker Services

The Docker Compose setup can include:

```text
postgres
pipeline
streamlit
dbt
```

### `postgres`

Runs the PostgreSQL database.

### `pipeline`

Runs the Python scraper and processing pipeline.

### `dbt`

Runs dbt transformations.

### `streamlit`

Runs the dashboard.

A simple execution flow can be:

```text
1. Start PostgreSQL
2. Run the scraper/pipeline
3. Run dbt models
4. Launch Streamlit dashboard
```

---

## 10. MVP Scope

The MVP should include:

```text
Controlled scraping from one or two job sources
Raw JSON/CSV storage
Python cleaning pipeline
Skill extraction using dictionary and regex
Skill normalization using synonym mapping
Rule-based seniority detection with Unknown category
PostgreSQL database
Data transformations using dbt
Market skill profiles by role
Streamlit dashboard
Manual student skill input
Role match scoring
Missing skill recommendation
Docker Compose setup
```

This version is realistic for a two-month internship project.

---

## 11. Out of Scope for the First Version

The following features should not be part of the first two-month version:

```text
CV upload
User accounts
Authentication
FastAPI backend
Airflow orchestration
MLflow experiment tracking
Kafka or real-time streaming
Cloud deployment
Advanced deep learning
Live scraping every time the dashboard runs
Complex recommendation models
```

These can be added later as future improvements.

---

## 12. Future Improvements

After the MVP is complete, possible improvements include:

```text
Add FastAPI backend
Add Airflow for pipeline orchestration
Add CV upload to extract student skills automatically
Add advanced NLP with embeddings
Add skill similarity matching
Add trend analysis over time
Add cloud deployment
Add user accounts
Add automated tests
Add data quality checks
Add MLflow if real ML models are introduced
```

---

## 13. Final One-Sentence Description

> SkillBridge scrapes job postings, extracts and standardizes required skills from job descriptions, transforms the data with PostgreSQL and dbt, and provides a Streamlit dashboard where students can compare their current skills with real market demand to find their closest data-related roles and missing skills.

---

## 14. Why This Project Is Useful

This project helps students stop guessing what to learn.

Instead of saying:

```text
I think I should learn Spark.
```

A student can say:

```text
According to current job postings, Spark appears in many Data Engineer roles, but PostgreSQL, Docker, and Airflow may be more common, so I should prioritize those first.
```

The final result is a practical system that combines:

```text
Data engineering
Web scraping
NLP-based skill extraction
PostgreSQL
Dbt transformations
Recommendation logic
Dashboarding
Dockerized deployment
```

The project is realistic for an internship, useful for students, and strong enough to demonstrate important data engineering concepts.
