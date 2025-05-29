import os
import streamlit as st
from dotenv import load_dotenv


# Load environment variables early
load_dotenv()

# Ensure OPENAI_API_KEY is set in environment before importing LangChain
os.environ["OPENAI_API_KEY"] = os.getenv("OPENAI_API_KEY")

import pyodbc
import openai
from dynamic_sql_generation import generate_sql_from_nl
from dynamic_sql_generation import select_prompt
import re
import contractions

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

DRIVER = os.getenv("Driver")
SERVER = os.getenv("Server")
DATABASE = os.getenv("Database")
UID = os.getenv("UID")
PWD = os.getenv("PWD")

openai.api_key = OPENAI_API_KEY

# Define column data types for Dw.fsales table
COLUMN_TYPES = {
    "DId": "int",
    "BillingDocument": "varchar",
    "BillingDocumentItem": "varchar",
    "BillingDate": "date",
    "SalesOfficeID": "int",
    "DistributionChannel": "varchar",
    "DisivisonCode": "varchar",
    "Route": "varchar",
    "RouteDescription": "varchar",
    "CustomerGroup": "varchar",
    "CustomerID": "varchar",
    "ProductHeirachy1": "varchar",
    "ProductHeirachy2": "varchar",
    "ProductHeirachy3": "varchar",
    "ProductHeirachy4": "varchar",
    "ProductHeirachy5": "varchar",
    "Materialgroup": "varchar",
    "SubMaterialgroup1": "varchar",
    "SubMaterialgroup2": "varchar",
    "SubMaterialgroup3": "varchar",
    "MaterialCode": "varchar",
    "SalesQuantity": "int",
    "SalesUnit": "varchar",
    "TotalAmount": "decimal",
    "TotalTax": "decimal",
    "NetAmount": "decimal",
    "EffectiveStartDate": "date",
    "EffectiveEndDate": "date",
    "IsActive": "bit",
    "SalesOrganizationCode": "varchar",
    "SalesOrgCodeDesc": "varchar",
    "ItemCategory": "varchar",
    "ShipToParty": "varchar"
}

import re

def fix_sql_value_quoting(sql_query):
    # Step 1: Fix broken values like 'ICE 'Cream'/FD'
    broken_value_fixes = {
        "ICE 'Cream'/FD": "ICE CREAM/FD",
        "ICE 'Cream' / FD": "ICE CREAM/FD",
        "'ICE 'Cream'/FD'": "'ICE CREAM/FD'",
    }
    for broken, correct in broken_value_fixes.items():
        sql_query = sql_query.replace(broken, correct)

    # Step 2: Replace ProductHeirachy1 with Materialgroup if "icecream/fd" or "icecream/fp" is mentioned
    if re.search(r"(ice[\s]?cream\s*/(fd|fp))", sql_query, re.IGNORECASE):
        sql_query = re.sub(
            r"(ProductHeirachy1\s*=\s*'[^']*')",
            "Materialgroup = 'ICE CREAM/FD'",
            sql_query,
            flags=re.IGNORECASE
        )
    elif re.search(r"\bice\s+cream\b", sql_query, re.IGNORECASE):
        sql_query = re.sub(
            r"(Materialgroup\s*=\s*'[^']*')",
            "ProductHeirachy1 = 'IceCream'",
            sql_query,
            flags=re.IGNORECASE
        )

    # Step 3: Fix quotes based on column data types
    for column, col_type in COLUMN_TYPES.items():
        pattern = re.compile(rf"({column}\s*=\s*)'([^']*)'", re.IGNORECASE)

        def replacer(match):
            prefix = match.group(1)
            value = match.group(2)
            if col_type in ['int', 'decimal', 'bit']:
                if value.isdigit() or value.lower() in ['true', 'false', '0', '1']:
                    return f"{prefix}{value}"
                else:
                    return match.group(0)
            else:
                return match.group(0)

        sql_query = pattern.sub(replacer, sql_query)

    return sql_query



import re

def validate_sql_query(sql_query):
    # Step 0: Clean leading SQL-like prefixes (e.g., "SQL:", "```sql", etc.)
    sql_query = sql_query.strip()
    sql_query = re.sub(r"^\s*(SQL:?|```sql)?\s*", "", sql_query, flags=re.IGNORECASE)

    # Optional: remove trailing ``` block or semicolon
    sql_query = re.sub(r"```$", "", sql_query).strip()
    sql_query = sql_query.rstrip(";").strip()

    # Step 1: Check for placeholder or example values in the SQL query
    placeholders = ['specific_salesofficeid', 'example_value', 'placeholder']
    for ph in placeholders:
        if ph.lower() in sql_query.lower():
            return False, f"SQL query contains placeholder value: {ph}"

    return True, ""


def execute_sql_query(sql_query):
    try:
        connection_string = (
            f"DRIVER={{{DRIVER}}};"
            f"SERVER={SERVER};"
            f"DATABASE={DATABASE};"
            f"UID={UID};"
            f"PWD={PWD}"
        )
        with pyodbc.connect(connection_string, timeout=10) as conn:
            cursor = conn.cursor()
            cursor.execute(sql_query)
            columns = [column[0] for column in cursor.description]
            rows = cursor.fetchall()
            results = [dict(zip(columns, row)) for row in rows]
            return results
    except Exception:
        st.error("There’s a server-side issue right now. Please restart your HFL server. it’s currently unable to fetch data due to heavy load. Thanks for your patience")
        return None

import re
import openai
import streamlit as st

def format_sql_results(results):
    formatted_rows = []
    for row in results:
        formatted_row = []
        for key, value in row.items():
            if isinstance(value, float):
                # Format with commas and 2 decimals
                formatted_value = f"{value:,.2f}"
            else:
                formatted_value = str(value)
            formatted_row.append(formatted_value)
        formatted_rows.append(", ".join(formatted_row))
    return "\n".join(formatted_rows)

def results_to_natural_language(results, user_query):
    print(results)
    if not results:
        return "Please wait."
    formatted_results= format_sql_results(results)
    print(formatted_results)
    # System prompt to reduce typos and ensure clear output
    system_prompt = (
        "You are a highly reliable business assistant specialized in summarizing SQL results into clear, accurate English.\n"
    "Your job is to summarize exactly what is present in the SQL result.\n"
    "Always include all rows and all column values exactly as shown in the SQL result.\n"
    "Do not skip, alter, abbreviate, interpret, or round any value — preserve full spelling, digits, and formatting.\n"
    "Never omit important words like 'Ghee', 'Laddu', or any product or name — always retain exact spellings.\n"
    "Do not explain how the result was calculated — just summarize what the result shows, in relation to the user query.\n"
    "Do not add assumptions, extra comments unless explicitly present in the SQL data.\n"
    "use icons (like %, ↑, 📈, etc.) or any relatable emojis"
    "never ever include '$'"
    "Never reword column names or values — copy them as-is. \n"
    "Ensure your summary is logically connected to the user's question, but based only on the data shown.\n"

)
    prompt_text = (
    f"User query: \"{user_query}\"\n\n"
    f"SQL result:\n{results}\n\n"
    "Write a simple but complete English summary using only the values shown above.\n"
    "Do not add any interpretations or exclude any row or column and never ever include '$'.\n"
    "Summary:"
)   

    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo-0125",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt_text}
            ],
            max_tokens=250,
            temperature=0.1,
            top_p=1.0,
            frequency_penalty=0.0,
            presence_penalty=0.0,
        )
        summary = response.choices[0].message['content'].strip()
        return summary

    except Exception as e:
        return f"Error generating summary: {e}"
custom_stop_words = {
    'rushi'
}
def remove_custom_stop_words(query, stop_words):
    tokens = query.lower().split()  # lowercase + split
    filtered = [word for word in tokens if word not in stop_words]
    return " ".join(filtered)

def main():
    st.set_page_config(page_title="AskHFL", page_icon="🗄️", layout="centered")

    st.markdown("""
        <div style="background-color: #28a745; padding: 1px; border-radius: 200px;">
            <h2 style="color: white; text-align: center;">Ask Heritage</h2>
        </div>
    """, unsafe_allow_html=True)

    user_query = st.text_area("Enter your query:",height=70)

    sql_query = None  # Initialize sql_query to avoid UnboundLocalError

    if st.button("Run Query"):
        if not user_query.strip():
            st.warning("Please enter a query.")
            return

        with st.spinner("Translating to SQL..."):
            # Preprocess the user query before generating SQL
            #preprocessed_query = contractions.fix(user_query)
            preprocessed_query =  remove_custom_stop_words(user_query, custom_stop_words)

        # Generate SQL from preprocessed query
        prompt_template = select_prompt(user_query)
        sql_query = generate_sql_from_nl(preprocessed_query)

        # Fix SQL value quoting based on column types and other fixes
        sql_query = fix_sql_value_quoting(sql_query)

        print(f"Generated SQL Query: {sql_query}")
        # Removed display of generated SQL query to hide it from front end for elegance
        # st.subheader("Generated SQL Query:")
        # st.code(sql_query, language="sql")

    # Validate SQL query for placeholders
    if sql_query is None:
        st.warning("hey, how can i assist you?")
        return

    valid, error_msg = validate_sql_query(sql_query)
    if not valid:
        st.error(error_msg)
        return

    with st.spinner("Executing..please wait searching in you database."):
        try:
            results = execute_sql_query(sql_query)
        except Exception:
            st.error("There’s a server-side issue right now. Please restart your HFL server. it’s currently unable to fetch data due to heavy load. Thanks for your patience")
            return

    if results is not None:
        summary = results_to_natural_language(results, user_query)
        print("The result from the llm: ",summary)
        st.markdown(f"""
    <div style="
        background: transparent;
        padding: 20px 15px;
        font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
        font-size: 16px;
        color: white;
        line-height: 1.5;
        max-width: 800px;
        border-radius: 8px;
        font-weight: 600;           
        border: 1px solid #ccc20a20;  /* very subtle border for shape */
    ">
        <h4 style="color: white; margin-bottom: 12px; font-weight: 600;">
            Your query result 🧾:
        </h4>
        <p style="white-space: pre-line;">{summary}</p>
    </div>
    """, unsafe_allow_html=True)

if __name__ == "__main__":
    main()
