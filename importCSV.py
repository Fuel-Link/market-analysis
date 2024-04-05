from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS
import pandas as pd
import os
from datetime import datetime

itoken = "a5bQCggAVLZqTrvecX4eL1KjpKZ8q_u_9GTehMJiD2MbDQXpSbvMIS4SoCYzkbpic9N9cSRjc5o-31dQBMg55g=="
org = "FuelLink"
url = "http://localhost:8086"

# Initialize the InfluxDB client
client = InfluxDBClient(url=url, token=itoken, org=org)
write_api = client.write_api(write_options=SYNCHRONOUS)

# Read your CSV data
df = pd.read_csv('Postos.csv')

# Convert DataFrame to a list of InfluxDB Point objects
points = []
for index, row in df.iterrows():
    point = Point("Prices")\
        .field("y", float(row['y']))\
        .time(row['ds'], WritePrecision.NS)
    points.append(point)

write_api.write(bucket="Gas-Prices", org=org, record=points)

print(points)




# query_api = client.query_api()

# query = """from(bucket: "Gas-Prices")
#  |> range(start: -1y)
#  |> filter(fn: (r) => r._measurement == "Prices")"""
# tables = query_api.query(query, org="Gas-pump")

# print(tables)

# for table in tables:
#   for record in table.records:
#     print(record)



# Close the client
client.close()
