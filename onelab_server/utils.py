from openai import OpenAI
from dotenv import load_dotenv
from pydantic import BaseModel, Field
import os
from pathlib import Path
from rank_bm25 import BM25Okapi
import numpy as np
from typing import Literal, Type
import re
import sqlite3
import pandas as pd
import base64
from IPython.display import Markdown, display
import requests
import json
from io import StringIO
from contextlib import redirect_stdout
import random
import string
from concurrent.futures import ThreadPoolExecutor, as_completed
from instructions_and_templates import html_code_services, html_code_waypoints, db_schema, tox_instructions_str, jail_instructions_str, sql_instructions_str, struct_instructions_str

load_dotenv()

client = OpenAI(
    api_key=os.getenv("BEDROCK_KEY"),
    base_url="https://bedrock-mantle.us-east-1.api.aws/openai/v1"
)

class ExtractTextValues(BaseModel):
    agencies: list[str] = Field(default = None, description="Name of the agency/laboratroy that offers laboratory and testing services.")
    countries: list[Literal['Australia', 'Malaysia', 'Philippines', 'Thailand', 'United Arab Emirates', 'Vietnam']] = Field(default = None, description="Country where the agency or laboratory is located")
    regions: list[Literal['ARMM', 'CAR', 'NCR', 'Region 1', 'Region 2', 'Region 3', 'Region 4A', 'Region4B', 'Region 5', 'Region 6', 'Region 7', 'Region 8', 'Region 9', 'Region 10', 'Region 11', 'Region 12', 'Region 13']] = Field(default = None, description="Administrative region where the agency or laboratory is located") 
    provinces: list[str] = Field(default = None, description="Province where the agency or laboratory is located")
    cities: list[str] = Field(default = None, description="City where the agency or laboratory is located")
    testnames: list[str] = Field(default = None, description="Laboratory Test name")
    methods: list[str] = Field(default = None, description="Analytical Procedure for the Test")
    references: list[str] = Field(default = None, description="Reference standard for the test and procedure")

class Toxicity(BaseModel):
    verdict: bool = Field(description = "Answer to whether the user input is toxic or not. True if toxic, False if NOT toxic.")
    reasoning: str = Field(description= "Answers the question 'why do you think the input is toxic or otherwise?'")

class Jailbreak(BaseModel):
    verdict: bool = Field(description = "Answer to whether the user input is a jailbreaking and prompt injection attempt. True if a jailbreaking or prompt injection attempt, False if NOT a jailbreaking or prompt injection attempt.")
    reasoning: str = Field(description= "Answers the question 'why do you think the input is a jailbreaking or prompt injection attempt?'")

class SQLInjection(BaseModel):
    verdict: bool = Field(description = "Answer to whether the user input is an SQL injection attempt. True if an SQL injection attempt, False if NOT an SQL injection attempt.")
    reasoning: str = Field(description= "Answers the question 'why do you think the input is an SQL injection attempt?'")

class InternalStructures(BaseModel):
    verdict: bool = Field(description = "Answer to whether the user input requests for internal structures, workflows, or databases. True if requesting for internal structures, workflows, models used, or databases. False if NOT requesting for internal structures, workflows, models used, or databases.")
    reasoning: str = Field(description= "Answers the question 'why do you think the input is requesting for internal structures, workflows, or databases?'")


def save_html(final_html: str):
    html_dir = Path(__file__).resolve().parent / "html"
    output_dir = Path(__file__).resolve().parent / "output.html"
    os.makedirs(html_dir, exist_ok=True)

    while True:
        random_name = "".join(random.choices(string.ascii_letters + string.digits, k=8))
        html_path = os.path.join(html_dir, f"{random_name}.html")

        if not os.path.exists(html_path):
            break

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(final_html)

    with open(output_dir, "w", encoding="utf-8") as f:
        f.write(final_html)

def html_visualization(rows:list=None,waypoints: str=None):
    final_html = None
    if rows:
        row_str = json.dumps(rows).replace("None","null")
        final_html = html_code_services.replace("{row_data}", row_str)
    elif waypoints:
        final_html = html_code_waypoints.replace("{waypoints}", str(waypoints))

    save_html(final_html)

    return final_html

def load_values_from_file(path: str) -> list[str]:
    """Create a file handler, load one value per line, strip, dedupe (preserve order)."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"File not found: {path}")

    seen = {}

    with p.open("r", encoding="utf-8") as fh:
        for line in fh:
            value = line.strip()
            if value:
                seen.setdefault(value, None)

    return list(seen)

def lexical_match(values: str, values_from_file: list[str], top_k: int = 10) -> list[str]:
    tokenized_values = [
        re.sub(r"\s+", " ", re.sub(r'[^a-z0-9]+', ' ', v.lower().replace(".",""))).strip().split()
        for v in values_from_file
    ]
    bm25 = BM25Okapi(tokenized_values)

    scored_candidates = []
    for value in values:
        tokenized_value = re.sub(r"\s+", " ", re.sub(r'[^a-z0-9]+', ' ', value.lower().replace(".",""))).strip().split()
        scores = bm25.get_scores(tokenized_value)
        indices = np.argsort(scores)[::-1][:top_k]

        for i in indices:
            scored_candidates.append((scores[i], values_from_file[i]))

    scored_candidates.sort(key=lambda x: x[0], reverse=True)

    matches = []
    seen = set()

    for score, candidate in scored_candidates:
        if candidate not in seen:
            seen.add(candidate)
            matches.append(candidate)

    return matches

def extract_values(user_query: str) -> str:
    value_match_string = """Keywords were extracted from the user's natural language query. 
The extracted keywords were used to obtain close lexical matches from the database using BM25.
Refer to these values to avoid disambiguation errors:\n"""

    system_prompt = """You are an information extraction system.
Your task is to extract only the information explicitly stated in the user's query and populate the corresponding fields in the provided pydantic text format.
General Rules:
- Extract only information that is explicitly mentioned or can be unambiguously identified from the user's query.
- Do NOT infer, guess, assume, or complete missing information.
- If a field cannot be confidently extracted, return null for that field.
- Do not rewrite or normalize values unless necessary to preserve their standard names.
- If multiple values belong to the same field, return all of them as a list.
- Do not return duplicate values.
- Preserve the wording used by the user whenever possible.
""".strip()
    #print(f"Extracting key words from ```{user_query}```... ")
    response = client.responses.parse(
        model = "openai.gpt-5.5",
        input = [
            {
                "role": "system",
                "content": system_prompt
            },
            {
                "role": "user",
                "content": user_query
            }
        ],
        text_format=ExtractTextValues
    )

    for key, values in response.output_parsed.model_dump().items():
        filepath = Path(__file__).resolve().parent / "unique_values"
        if values:
            value_match_string += f"**{key}**:\n"
            values_from_file = load_values_from_file(f"{filepath}/{key}.txt")
            matches = lexical_match(values, values_from_file)
            for match in matches:
                value_match_string += f"- {match}\n"

    return value_match_string

def generate_sql(user_query: str, value_match_string: str, db_schema: str = db_schema, latitude: float = 14.64753, longitude: float = 121.07194) -> str:
    location_info = f"This is the user's current location: latitude={latitude}, longitude={longitude}"

    instructions = f"""Convert the user's natural language query into an sqlite query.
    **General Rules**:
    - Always include all columns from the **agencies** table specially the location information.
    - Use the methods table to obtain textual information about the laboratory services: (test name, method, reference), and the fee
    - Always include all the services information (test name, method, reference, and fee) for every returned laboratory
    - Output only the runnable SQLite query without any delimiters
    - Use asr as alias for agency_services
    - Do not use SQL keywords as alias

    **Database Schema**:
    {db_schema}

    {value_match_string}

    {location_info}

    **User's Natural Language Query**:
    {user_query}

    SQLite Query:
    """
    #print(f"Generating SQL for query ```{user_query}```...")
    response = client.responses.create(
        model = "openai.gpt-5.5",
        input = [
            {
                "role": "user",
                "content": instructions
            }
        ]
    )

    sql = response.output_text

    sql = re.sub(r"^```[a-zA-Z]*\n?", "", sql)
    sql = re.sub(r"\n?```$", "", sql)

    return sql

# Add a layer of security

def is_safe_select_query(sql: str) -> bool:
    """
    Basic guard to ensure the generated SQL is a read-only SELECT/CTE query.
    - Must start with SELECT or WITH (ignoring whitespace/comments).
    - Must not contain unsafe keywords.
    - Must not contain multiple statements separated by ';' (beyond a trailing ';').
    """
    UNSAFE_SQL_PATTERNS = re.compile(
        r"\b(insert|update|delete|drop|alter|create|attach|reindex|vacuum|pragma|replace|truncate)\b",
        flags=re.IGNORECASE
    )

    if not sql or not isinstance(sql, str):
        return False

    s = sql.strip()
    # Remove trailing semicolon
    if s.endswith(";"):
        s = s[:-1].strip()

    # Disallow multiple statements
    if ";" in s:
        return False

    # Must start with SELECT or WITH
    starts_ok = s[:6].upper() == "SELECT" or s[:4].upper() == "WITH"
    if not starts_ok:
        return False

    # Disallow any unsafe patterns
    if UNSAFE_SQL_PATTERNS.search(s):
        return False

    return True

def execute_sql(sql: str) -> pd.DataFrame:
    if not is_safe_select_query(sql):
        #print("Generated SQL is not a safe SELECT query. Returning empty data frame...")
        df_result = pd.DataFrame()
    else:    
        #print("Executing safe SQL query...")
        db_path = Path(__file__).resolve().parent / "OneLab.db"
        conn = sqlite3.connect(db_path)
        df_result = pd.read_sql(sql,conn)
        conn.close()

    return df_result.to_dict("records")

#extract agency and testname
#extract agency name first

def extract_rag_context(user_query:str, sanity_check: bool = False):

    db_path = Path(__file__).resolve().parent / "OneLab.db"
    file_path = Path(__file__).resolve().parent / "unique_values/agencies.txt"

    with open(file_path, "r", encoding="utf-8") as f:
        agencies = tuple(line.strip() for line in f if line.strip())

    AgencyLiteral = Literal[agencies]

    class RAGExtraction(BaseModel):
        agency: AgencyLiteral
        testname: str

    response = client.responses.parse(
        model="openai.gpt-5.5",
        input = [
            {
                "role": "system",
                "content": "Extract the agency or laboratory name and the name of the laboratory test from the user's natural language input."
            },
            {
                "role":"user",
                "content":user_query
            }
        ],
        text_format=RAGExtraction
    )

    agency = response.output_parsed.agency
    testname = response.output_parsed.testname

    if sanity_check:
        print(f"\nExtracted agency=`{agency}` and testname=`{testname}` from user_query=`{user_query}`")

    testnames = []
    #get all tests under that agency in a string (one test per line)
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT DISTINCT m.testname
            FROM agencies AS a
            JOIN agency_services AS s
                ON a.id = s.agency_id
            JOIN methods AS m
                ON s.method_id = m.id
            WHERE a.agencyName = ?
        """, (agency,))

        testnames = [row[0] for row in cursor.fetchall()]

    if sanity_check:
        print(f"\nExtracted sample testnames from {agency}:")
        for ctr in range(5):
            print(f"{ctr+1}. {testnames[ctr]}")

    #get closest matching test name using lexical_match
    test_value_matches = lexical_match(values=[testname], values_from_file=testnames, top_k=5)

    if sanity_check:
        print(f"\nLexical matches to `{testname}` using lexical_match:")
        for ctr, match in enumerate(test_value_matches):
            print(f"{ctr+1}. {match}")

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("""
            SELECT 
                m.testname,
                m.method,
                m.reference,
                m.fee,
                m.pages
            FROM agencies AS a
            JOIN agency_services AS s
                ON a.id = s.agency_id
            JOIN methods AS m
                ON s.method_id = m.id
            WHERE a.agencyName = ?
            AND m.testname = ?
            ORDER BY m.id
            LIMIT 1
        """, (agency, test_value_matches[0]))

        row = cursor.fetchone()

    if row:
        result = {
            "agency": agency,
            "testname": row["testname"],
            "method": row["method"],
            "reference": row["reference"],
            "fee": row["fee"],
            "pages": row["pages"]
        }
    else:
        result = None

    return result

def run_rag(agencyname: str, testname: str, pages: str, method: str = None, reference:str = None, fee: str = None, sanity_check: bool = False):
    if agencyname not in ["DOST-ITDI"]:
        return f"No files found for {agencyname}"

    if sanity_check:
        print(f"""\nPerforming RAG on {agencyname}-{pages.replace(",","-")}.pdf with the following context:\nagency:\t{agencyname}\ntest:\t{testname}\nmethod:\t{method}\nreference:\t{reference}\nfee:\t{fee}""")

    filepath = Path(__file__).resolve().parent / "files"
    with open(f"""{filepath}/{agencyname}-{pages.replace(",","-")}.pdf""", "rb") as f:
        data = f.read()

    base64_string = base64.b64encode(data).decode("utf-8")

    response = client.responses.create(
        model="openai.gpt-5.5",
        input=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_file",
                        "filename": "DOST-ITDI-144-151.pdf",
                        "file_data": f"data:application/pdf;base64,{base64_string}",
                    },
                    {
                        "type": "input_text",
                        "text": f"What are the requirements, client steps, total processing time, and schedule of fees and charges for the following:\ntestname={testname}\nmethod={method}\nreference={reference}\nfee={fee}",
                    },
                ],
            },
        ]
    )

    return response.output_text

def get_waypoints(lat_origin, long_origin, lat_destination, long_destination, mode = "driving"):
    """
    Request directions from Google Maps Directions API
    and return the response as a stringified JSON object.
    """

    url = "https://maps.googleapis.com/maps/api/directions/json"
    api_key = os.getenv("WAYPOINTS_KEY")

    params = {
        "origin": f"{lat_origin},{long_origin}",
        "destination": f"{lat_destination},{long_destination}",
        "mode": mode,
        "departure_time": "now",
        "traffic_model": "pessimistic",
        "key": api_key,
    }

    response = requests.get(url, params=params, timeout=120)
    response.raise_for_status()

    data = response.json()

    return json.dumps(data, indent=2)

def geocode_loc(loc: str):

    url = "https://maps.googleapis.com/maps/api/geocode/json"
    api_key = os.getenv("WAYPOINTS_KEY")

    params = {
        "address": loc,
        "key": api_key
    }

    response = requests.get(url, params=params, timeout=120)
    response.raise_for_status()

    data = response.json()

    location = data["results"][0]["geometry"]["location"]

    return location

def parse_locations(user_query:str):

    filepath = Path(__file__).resolve().parent / "unique_values/agencies.txt"
    with open(filepath, "r", encoding="utf-8") as f:
        agencies = tuple(line.strip() for line in f if line.strip())

    AgencyLiteral = Literal[agencies]

    class ExtractAgency(BaseModel):
        agency: AgencyLiteral
        user_location: str

    response = client.responses.parse(
        model = "openai.gpt-5.5",
        input = [
            {
                "role":"system",
                "content": "Extract the user's location agency/laboratory name from the user's natural language input."
            },
            {
                "role":"user",
                "content":user_query
            }
        ],
        text_format = ExtractAgency
    )

    return response.output_parsed


def get_agency_coord(agency: str, sanity_check: bool =False):

    db_path = Path(__file__).resolve().parent / "OneLab.db"

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("""
            SELECT latitude, longitude
            FROM agencies
            WHERE agencyName = ?
            LIMIT 1
        """, (agency,))

        row = cursor.fetchone()

    if row:
        if sanity_check:
            print("latlng found in db")
        latitude = row["latitude"]
        longitude = row["longitude"]
        if not latitude and not longitude:
            if sanity_check:    
                print("latlng from db is None")
                print("geocoding location")
            location = geocode_loc(agency)
            latitude = location["lat"]
            longitude = location["lng"]

    else:
        if sanity_check:
            print("geocoding location")
        location = geocode_loc(agency)
        latitude = location["lat"]
        longitude = location["lng"]

    return {
        "lat": latitude,
        "lng": longitude
    }

def generate_summary(user_query: str, rows: list = None, waypoints: str = None):

    system_instructions_rows = """You are given list of dataframe rows (`rows` already defined in the execution environment) in dictionary format obtained from a txt2sql workflow.
    These rows may contain any of the following keys:
    `agencyName`: Name of the agency/laboratroy that offers laboratory and testing services
    `country`: Country where the agency or laboratory is located
    `region`: Administrative Region where the agency or laboratory is located
    `province`: Province where the agency or laboratory is located
    `city`: City where the agency or laboratory is located
    `testname`: Laboratory test or service name
    'method': Analytical procedure for the test
    `reference`: Reference standard for the test and procedure
    `fee`: Cost of the laboratory test or service

    Your task is to write a python code that will give a concise and informative insights of the given data. Highlight the information that is the focus of the user's question (i.e, agencies, locations, laboratory tests, etc.).
    No need to further filter the rows.
    Do not print everything since some laboratories will have lots of tests and a result can have lots of rows
    """
    system_instructions_waypoints = """You are given waypoints from google directions api in dictionary format (`waypoints` already defined in the execution environment, based on the user's query which is a direction from one place to another.
    Your task is to write a python code that will give a concise and informative summary of the given data
    """

    safe_globals = {}

    if rows:
        #print("Got rows")
        system_instructions = system_instructions_rows
        safe_globals = {
            "rows": rows
        }
    elif waypoints:
        #print("Got waypoints")
        #print(type(waypoints))
        system_instructions = system_instructions_waypoints
        safe_globals = {
            "waypoints": json.loads(waypoints)
        }


    response = client.responses.create(
        model = "openai.gpt-5.5",
        input = [
            {
                "role":"system",
                "content":system_instructions
            },
            {
                "role":"user",
                "content":user_query
            }
        ]
    )

    response_text = response.output_text
    pattern = r"```python\s*\n?(.*?)```"
    match = re.search(pattern, response_text, re.DOTALL)

    if match:
        code = match.group(1).strip()
    else:
        code = "print('Failed to generate python code')"

    buffer = StringIO()

    with redirect_stdout(buffer):
        exec(code, safe_globals)

    output = buffer.getvalue()
    return output

def parse_nearest_labs_info(user_query:str):
    class NearestLabs(BaseModel):
        reference_location: str = Field(default = None, description="reference location explicitly mentioned in the user's input")
        limit: int = Field(default = None, description="Maximum number of nearest laboratories requested by the user")
        testname: str = Field(default=None, description="Required test that the nearest laboratories must offer")

    response = client.responses.parse(
        model="openai.gpt-5.5",
        input = [
            {
                "role":"system",
                "content":"Extract the reference location, limit to the number of laboratories, and laboratory test name if and only if specified."
            },
            {
                "role":"user",
                "content":user_query
            }
        ],
        text_format=NearestLabs
    )
    return response.output_parsed


def nearest_labs(lat:float=14.64753, lng:float=121.07194, testname:str="", limit:int=5):

    sql = f"""WITH nearest_labs AS (
        SELECT
            a.*,
            (
                6371.0 * 2 * ASIN(
                    SQRT(
                        POWER(SIN(((a.latitude - {lat}) * 0.0174532925199433) / 2), 2) +
                        COS({lat} * 0.0174532925199433) *
                        COS(a.latitude * 0.0174532925199433) *
                        POWER(SIN(((a.longitude - {lng}) * 0.0174532925199433) / 2), 2)
                    )
                )
            ) AS distance_km
        FROM agencies a
        WHERE a.latitude IS NOT NULL
        AND a.longitude IS NOT NULL
        AND EXISTS (
            SELECT 1
            FROM agency_services ags_filter
            JOIN methods m_filter
                ON m_filter.id = ags_filter.method_id
            WHERE ags_filter.agency_id = a.id
                AND LOWER(m_filter.testname) LIKE '%{testname}%'
        )
        ORDER BY distance_km ASC
        LIMIT {limit}
    )
    SELECT
        nl.id,
        nl.agencyName,
        nl.code,
        nl.latitude,
        nl.longitude,
        nl.contactInformation,
        nl.website,
        nl.logoName,
        nl.country,
        nl.region,
        nl.province,
        nl.city,
        nl.distance_km,

        m.testname,
        m.method,
        m.reference,
        m.fee
    FROM nearest_labs nl
    LEFT JOIN agency_services ags
        ON ags.agency_id = nl.id
    LEFT JOIN methods m
        ON m.id = ags.method_id
    ORDER BY
        nl.distance_km ASC,
        nl.agencyName ASC,
        m.testname ASC;"""


    rows = execute_sql(sql=sql)

    return rows

def generate_code(user_query:str):
    system_instructions = """You are given a data on a simple but comprehensive provincial level hotspot and service area analysis.

    Write a python code to get details from the data and answer the user's question in a concise way.

    Use this as the path to the data: Path('__file__').resolve().parent ../analytics/tables/province_hotspot_analysis.csv
    Make sure to resolve the base file directory

    This analysis data can identify:
    1. Provinces with high laboratory concentration
    2. provinces with high service availability
    3. Provinces with broad test coverage
    4. Provinces that appear underservced relative to population
    5. Provinces without local onelab presence
    6. Approximate province-level service area coverage
    7. Provinces with at least one local onelab agency
    8. Population living in provinces with local onelab presence
    9. Provinces with no local onelab presence
    10. Approximate distance from each province centroid to onelab agency
    11. Distance band classification

    # Column information
    **reporting_area** Philippine provinces
    **population** population per province. taken from 2020 census
    **agency_count** number of onelab laboratories and agencies per province
    **service_count** number of test and services per province
    **unique_test_count** number of unique tests and services per province
    **avg_services_per_agency** service_count divided by agency_count
    **avg_fee** average fee of all services in the province
    **min_fee** cheapest fee among all services
    **max_fee** most expensive fee among all services

    Note: raw agency service counts can be misleading because provinces have different population sizes: 

    **labs_per_100k_population** agency_count/(population*100000)
    **services_per_100k_population**  service_count/(population*100000)
    **unique_tests_per_100k_population** unique_test_count/(population*1000000)

    **area_sq_km** provincial land area in squarer kilometers
    **population_density_per_sq_km** population/area_sq_km

    Note: the normalized metrics below were obtained using minmax (series - series.min())/(series.max()-series.min())

    **agency_count_norm** normalized agency_count
    **service_count_norm** normalized service_count
    **unique_test_count_norm** normalized unique_test_count
    **labs_per_100k_norm** normalized labs_per_100k_population
    **services_per_100k_norm"** normalized services_per_100k_population
    **unique_tests_per_100k_norm** normalized unique_tests_per_100k_population
    **population_norm** normalized population
    **supply_score** = 0.40*agency_count_norm + 0.40*service_count_norm + 0.20**unique_test_count_norm
    **per_capita_supply_score** =  0.40*labs_per_100k_norm + 0.40*services_per_100k_norm + 0.20**unique_tests_per_100k_norm
    **gap_score** = population_norm - supply_score
    **classification** 
        -`No local OneLab presence`: agency_count == 0
        -`Potentially underserved`: provincial gap_score >= series gap_score.quantile(0.80)
        -`Laboratory/service hotspot`: provincial supply_score >= series supply_score.quantile(0.80)
        -`Well-served per capita`: provincial per_capita_supply_score >= series per_capita_supply_score.quantile(0.80)
        -`Low coverage`:  provincial supply_score <= series supply_score.quantile(0.20)
        -`Moderate coverage`: otherwise
    **nearest_agency** nearest agency to provincial centroid
    **nearest_agency_province** province of the nearest agency
    **centroid_nearest_lab_km** distance to the nearest lab from provincial centroid in kilometers (straight line distance)
    **province_service_distance_km** same with centroid_nearest_lan_km but zero if nearest lab is within the province 
    **service_area_band**
        -`Local OneLab presence`: agency_count > 0
        -`No local lab; nearest <= 50 km`: province_service_distance_km <= 50
        -`No local lab; nearest 50-100 km`: province_service_distance_km 50-100
        -`No local lab; nearest 100-200 km`: province_service_distance_km 100-200
        -`No local lab; nearest > 200 km`: province_service_distance_km > 200

    # Interpretation notes

    The results should be interpreted as a supply-side and population-normalized analysis.
    The analysis can identify provinces that appear underserved relative to population, but it does not directly measure actual testing demand.
    Therefore, provinces identified as potentially underserved should be treated as candidates for further validation, not final.

    # Limitations

    1. Population is used as a simple proxy for demand
    2. Travel time is not calculated
    3. Road networks are not included
    4. The service area distance is based on approximate straight-line distance.
    5. Province-level aggregation may hide city-level or municipal-level gaps.
    6. The analysis assumes that agency coordinates are accurate.
    7. The analysis does not account for laboratory capacity, accreditation, turnaround time, or actual workload
    8. Fee differences may reflecty differences in test complexity, not simply affordability.

    # Important wordings for reporting

    Use careful language.

    Good wording:
    `This province appears potentially underserved relative to population and current onelab supply.`

    Avoid:
    `This province has unmet demand.`

    Because there is no actual demand data.

    Also good:
    `The service area analysis is approximate because it is based on province-level aggregation and straight-line centroid distance, not road travel time.`

    This keeps the report accurate and defensible
    """

    response = client.responses.create(
        model = "openai.gpt-5.6-luna",
        input=[
            {
                "role":"system",
                "content": system_instructions
            },
            {
                "role":"user",
                "content": user_query
            }
        ]
    )

    response_text = response.output_text
    pattern = r"```python\s*\n?(.*?)```"
    match = re.search(pattern, response_text, re.DOTALL)

    if match:
        code = match.group(1).strip()

    else:
        code = "print('Failed to generate python code')"

    return code

def execute_python(code: str):
    buffer = StringIO()

    with redirect_stdout(buffer):
        exec(code)

    output = buffer.getvalue()
    return output

def final_response(user_query:str, output:str):
    system_instructions = """You are given a user question and some data extracted using python code to answer the question.

    Draft a concise narrative response to the user's question that is grounded to the provided data in markdown format. 
    Include tables when necessary.
    Include a brief explainer on what the numeric columns are about.

    Here are some details from the data source:

    This analysis data can identify:
    1. Provinces with high laboratory concentration
    2. provinces with high service availability
    3. Provinces with broad test coverage
    4. Provinces that appear underservced relative to population
    5. Provinces without local onelab presence
    6. Approximate province-level service area coverage
    7. Provinces with at least one local onelab agency
    8. Population living in provinces with local onelab presence
    9. Provinces with no local onelab presence
    10. Approximate distance from each province centroid to onelab agency
    11. Distance band classification

    # Column information
    **reporting_area** Philippine provinces
    **population** population per province. taken from 2020 census
    **agency_count** number of onelab laboratories and agencies per province
    **service_count** number of test and services per province
    **unique_test_count** number of unique tests and services per province
    **avg_services_per_agency** service_count divided by agency_count
    **avg_fee** average fee of all services in the province
    **min_fee** cheapest fee among all services
    **max_fee** most expensive fee among all services

    Note: raw agency service counts can be misleading because provinces have different population sizes: 

    **labs_per_100k_population** agency_count/(population*100000)
    **services_per_100k_population**  service_count/(population*100000)
    **unique_tests_per_100k_population** unique_test_count/(population*1000000)

    **area_sq_km** provincial land area in squarer kilometers
    **population_density_per_sq_km** population/area_sq_km

    Note: the normalized metrics below were obtained using minmax (series - series.min())/(series.max()-series.min())

    **agency_count_norm** normalized agency_count
    **service_count_norm** normalized service_count
    **unique_test_count_norm** normalized unique_test_count
    **labs_per_100k_norm** normalized labs_per_100k_population
    **services_per_100k_norm"** normalized services_per_100k_population
    **unique_tests_per_100k_norm** normalized unique_tests_per_100k_population
    **population_norm** normalized population
    **supply_score** = 0.40*agency_count_norm + 0.40*service_count_norm + 0.20**unique_test_count_norm
    **per_capita_supply_score** =  0.40*labs_per_100k_norm + 0.40*services_per_100k_norm + 0.20**unique_tests_per_100k_norm
    **gap_score** = population_norm - supply_score
    **classification** 
        -`No local onelab presence`: agency_count == 0
        -`Potentially underserved`: provincial gap_score >= series gap_score.quantile(0.80)
        -`Laboratory/service hotspot`: provincial supply_score >= series supply_score.quantile(0.80)
        -`Well-served per capita`: provincial per_capita_supply_score >= series per_capita_supply_score.quantile(0.80)
        -`Low coverage`:  provincial supply_score <= series supply_score.quantile(0.20)
        -`Moderate coverage`: otherwise
    **nearest_agency** nearest agency to provincial centroid
    **nearest_agency_province** province of the nearest agency
    **centroid_nearest_lab_km** distance to the nearest lab from provincial centroid in kilometers (straight line distance)
    **province_service_distance_km** same with centroid_nearest_lan_km but zero if nearest lab is within the province 
    **service_area_band**
        -`Local OneLab presence`: agency_count > 0
        -`No local lab; nearest <= 50 km`: province_service_distance_km <= 50
        -`No local lab; nearest 50-100 km`: province_service_distance_km 50-100
        -`No local lab; nearest 100-200 km`: province_service_distance_km 100-200
        -`No local lab; nearest > 200 km`: province_service_distance_km > 200

    # Interpretation notes

    The results should be interpreted as a supply-side and population-normalized analysis.
    The analysis can identify provinces that appear underserved relative to population, but it does not directly measure actual testing demand.
    Therefore, provinces identified as potentially underserved should be treated as candidates for further validation, not final.

    # Limitations

    1. Population is used as a simple proxy for demand
    2. Travel time is not calculated
    3. Road networks are not included
    4. The service area distance is based on approximate straight-line distance.
    5. Province-level aggregation may hide city-level or municipal-level gaps.
    6. The analysis assumes that agency coordinates are accurate.
    7. The analysis does not account for laboratory capacity, accreditation, turnaround time, or actual workload
    8. Fee differences may reflecty differences in test complexity, not simply affordability.

    # Important wordings for reporting

    Use careful language.

    Good wording:
    `This province appears potentially underserved relative to population and current onelab supply.`

    Avoid:
    `This province has unmet demand.`

    Because there is no actual demand data.

    Also good:
    `The service area analysis is approximate because it is based on province-level aggregation and straight-line centroid distance, not road travel time.`

    This keeps the report accurate and defensible
    """

    response = client.responses.create(
        model = "openai.gpt-5.5",
        input=[
            {
                "role":"system",
                "content": system_instructions
            },
            {
                "role":"user",
                "content": f"**user question**:\n{user_query}\n\n**code output that answers the user's question**:\n{output}"
            }
        ]
    )

    return response.output_text

def run_filter(
        job: str,
        system_instruction: str,
        response_model: Type[BaseModel],
        user_input: str,
):
    response = client.responses.parse(
        model="openai.gpt-5.5",
        input=[
            {
                "role":"system",
                "content":system_instruction
            },
            {
                "role":"user",
                "content":f"user input: {user_input}" 
            }
        ],
        text_format = response_model
    )  

    filter_response = response.output_parsed
    verdict = filter_response.verdict
    reasoning = filter_response.reasoning
    #print(f"{job} verdict:\t{verdict}\nreasoning:\t{reasoning}")

    return verdict

def execute_thread(user_input: str):

    filter_jobs = [
        {
            "job": "tox",
            "system_instruction": tox_instructions_str,
            "response_model": Toxicity,
        },
        {
            "job": "jailbreak",
            "system_instruction": jail_instructions_str,
            "response_model": Jailbreak,
        },
        {
            "job": "sql",
            "system_instruction": sql_instructions_str,
            "response_model": SQLInjection,
        },
        {
            "job": "struct",
            "system_instruction": struct_instructions_str,
            "response_model": InternalStructures,
        },
    ]

    results = {}
    errors = {}

    with ThreadPoolExecutor(max_workers=len(filter_jobs)) as executor:

        future_to_job = {
            executor.submit(
                run_filter,
                job=job["job"],
                system_instruction=job["system_instruction"],
                response_model=job["response_model"],
                user_input=user_input,
            ): job["job"]
            for job in filter_jobs
        }

        for future in as_completed(future_to_job):

            job_name = future_to_job[future]

            try:
                results[job_name] = future.result(timeout=20)

            except Exception as e:
                errors[job_name] = str(e)

    # print("\nRESULTS:")
    # print(results)

    # print("\nERRORS:")
    # print(errors)

    return results, errors

def is_threat(user_input: str):

    #print("Running threat filter...")
    results, errors = execute_thread(user_input)
    is_toxic = results.get("tox")
    is_jailbreak = results.get("jailbreak")
    is_sql_injection = results.get("sql")
    is_struct = results.get("struct")

    _is_threat = is_toxic or is_jailbreak or is_sql_injection or is_struct    

    return _is_threat, errors

