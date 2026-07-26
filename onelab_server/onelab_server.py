from concurrent.futures import ThreadPoolExecutor
from typing import Tuple
from instructions_and_templates import db_schema
from mcp.server.fastmcp import FastMCP
from utils import (
    html_visualization,
    extract_values,
    generate_sql,
    execute_sql,
    extract_rag_context,
    run_rag,
    get_waypoints,
    geocode_loc,
    parse_locations,
    get_agency_coord,
    generate_summary,
    parse_nearest_labs_info,
    nearest_labs,
    generate_code,
    execute_python,
    final_response,
)

mcp = FastMCP("onelab_server")

@mcp.tool()
def txt2sql_workflow(user_query: str) -> Tuple[str,str]:
    """
    Query the OneLab.db using natural language input.
    Answers queries on information on the location of laboratories and agencies as well as the services that they offer.

    Args:
        user_query: natural language query

    Returns:
        response: textual summary of the retrieved rows
        final_html: html map visualization of the retrieved rows is string format
    """
    value_match_string = extract_values(user_query=user_query)
    sql = generate_sql(user_query=user_query, value_match_string=value_match_string, db_schema=db_schema)
    rows = execute_sql(sql=sql)
    final_html = html_visualization(rows=rows)
    response = generate_summary(user_query=user_query, rows=rows)
    return response, final_html

@mcp.tool()
def rag_workflow(user_query: str) -> Tuple[str,None]:
    """
    Perform RAG on available citizen's charter and service catalog files
    Provides information on client steps, processes, requirements, or information on how to avail of a particular service in an agency

    Args:
            user_query: natural language query

    Returns:
            response: textual response grounded on available related documents
    """
    result = extract_rag_context(user_query=user_query, sanity_check=False)
    response = run_rag(agencyname=result['agency'], testname=result['testname'], pages=result['pages'], method=result['method'], reference=result['reference'], fee=str(result['fee']), sanity_check=False)
    return response, None

@mcp.tool()
def waypoints_workflow(user_query:str) -> Tuple[str,str]:
    """
    Uses google's directions API to provide waypoints
    Answers questions on how to go to a particular agency or laboratory from a certain location

    Args:
        user_query: natural language query

    Returns:
        response: textual summary of the retrieved rows
        final_html: html map visualization of the retrieved rows is string format
    """
    locations = parse_locations(user_query)
    agency = locations.agency
    user_loc = locations.user_location

    with ThreadPoolExecutor(max_workers=2) as executor:
        destination_future = executor.submit(get_agency_coord, agency)
        origin_future = executor.submit(geocode_loc, user_loc)

        destination = destination_future.result()
        origin = origin_future.result()

    waypoints = get_waypoints(origin['lat'], origin['lng'], destination['lat'], destination['lng'])
    final_html = html_visualization(waypoints=waypoints)
    response = generate_summary(user_query=user_query, waypoints=waypoints)
    return response, final_html

@mcp.tool()
def nearest_labs_workflow(user_query: str) -> Tuple[str,str]:   
    """
    Uses and executes an SQLite template to provide infromation on nearest laboratories and/or the services that they offer given a reference location

    Args:
        user_query: natural language query

    Returns:
        response: textual summary of the retrieved rows
        final_html: html map visualization of the retrieved rows is string format    
    """ 
    response = parse_nearest_labs_info(user_query)
    #print(response)
    kwargs = {}
    if response.reference_location:
        reference_location_coord = geocode_loc(response.reference_location)
        lat = reference_location_coord['lat']
        lng = reference_location_coord['lng']
        kwargs["lat"]=lat
        kwargs["lng"]=lng
    if response.limit:
        kwargs["limit"] = response.limit
    if response.testname:
        kwargs["testname"] = response.testname
    #print(kwargs)
    rows  = nearest_labs(**kwargs)
    final_html = html_visualization(rows=rows)
    response = generate_summary(user_query=user_query, rows=rows)
    return response, final_html

@mcp.tool()
def analysis_workflow(user_query:str) -> Tuple[str,None]:
    """
    Performs code execution to access csv data.
    Provides answers to hotspot and service area analysis questions (data is for provincial level analysis only)

    Args:
        user_query: natural language query

    Returns:
        response: textual summary of the retrieved data
    """
    code = generate_code(user_query)
    output = execute_python(code)
    response = final_response(user_query=user_query, output=output)
    return response, None

if __name__=="__main__":
    mcp.run(transport='stdio')
