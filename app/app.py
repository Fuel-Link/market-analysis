import os
import json
import sqlite3
import requests
import binascii
import pandas as pd
from prophet import Prophet
from datetime import datetime
from influxdb_client.client.write_api import SYNCHRONOUS
from flask import Flask, render_template, request, jsonify
from influxdb_client import InfluxDBClient, Point, WritePrecision

app = Flask(__name__)

DATABASE = '/app/data/orgs.db'

def get_db():
    conn = sqlite3.connect(DATABASE)
    return conn

def create_table():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS orgs (
                        org TEXT PRIMARY KEY,
                        url TEXT NOT NULL,
                        bucket TEXT NOT NULL,
                        measurement TEXT NOT NULL,
                        field TEXT NOT NULL,
                        authToken TEXT UNIQUE NOT NULL
                    )''')
    conn.commit()
    conn.close()

@app.route('/predict', methods=["GET"])
def predict():
	
	org = request.args.get('org')
	authToken = request.args.get("authToken")
	token = request.args.get('token')
	days = request.args.get('days',default=15)

	if not org or not token or not authToken:
		return jsonify({'error': 'org, token and authToken parameters are required'}), 400
	
	conn = get_db()
	cursor = conn.cursor()

	cursor.execute('SELECT * FROM orgs WHERE org = ? AND authToken = ?', (org, authToken))
	client = cursor.fetchone()

	if client is None:
		return jsonify({'error': 'organization not found or authentication failed'}), 404
	
	url = client[1]
	bucket = client[2]
	measurement = client[3]
	field = client[4]

	try:
		read_client = InfluxDBClient(url=url, token=token, org=org, timeout=60000)
		buckets_api = read_client.buckets_api()

		if not buckets_api.find_bucket_by_name(bucket):
			# Call the updateData function if bucket does not exist
			updateData(org, token, url, bucket, measurement, field)

		# Construct the Flux query
		query = f'''
		from(bucket: "{bucket}")
			|> range(start: 0)
			|> filter(fn: (r) => r._measurement == "{measurement}" and r._field == "{field}")
			|> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
		'''

		# Query InfluxDB
		result = read_client.query_api().query_data_frame(query=query, org=org)
		if result.empty:
			return jsonify({'error': 'No data found for the specified date range'}), 404

		# Prepare DataFrame for Prophet
		df = result.rename(columns={"_time": "ds", field: "y"})
		df['ds'] = df['ds'].dt.strftime('%a, %d %b %Y %H:%M:%S GMT')

		actual_values = df[['ds', 'y']].tail(int(days)).to_json(orient='records', date_format='iso')
		actual_values = json.loads(actual_values)

		m = Prophet()
		m.fit(df)

		future = m.make_future_dataframe(periods=int(days))
		future.tail()

		forecast = m.predict(future)

		predictions = forecast[['ds', 'yhat']].tail(int(days))
		predictions_list = predictions.to_dict('records')

		read_client.close()
		return jsonify({'predictions': predictions_list, 'real': actual_values})

	except Exception as e:
		print(f"Error: {e}")
		return jsonify({'error': str(e)}), 500


@app.route('/addClient', methods=['POST'])
def addClient():
	org = request.args.get("org")
	url = request.args.get("url")
	bucket = request.args.get("bucket")
	measurement = request.args.get("measurement")
	field = request.args.get("field")

	if not url or not org or not bucket or not measurement or not field:
		return jsonify({"error": "org, url, bucket, measurement and field parameters are required."}), 400

	authToken = binascii.hexlify(os.urandom(20)).decode()

	conn = get_db()
	cursor = conn.cursor()

	try:
		cursor.execute('''INSERT INTO orgs (org, url, bucket, measurement, field, authToken)
							VALUES (?, ?, ?, ?, ?, ?)''', (org, url, bucket, measurement, field, authToken))
		conn.commit()
	except sqlite3.IntegrityError as e:
		conn.rollback()
		return jsonify({"error": str(e)}), 500
	finally:
		conn.close()

	return jsonify({"message": "User added successfully", "authToken":authToken}), 200


@app.route('/updateClient', methods=['PUT'])
def updateClient():
	org = request.args.get("org")
	authToken = request.args.get("authToken")
	url = request.args.get("url")
	bucket = request.args.get("bucket")
	measurement = request.args.get("measurement")
	field = request.args.get("field")

	if not org or not authToken:
		return jsonify({"error": "org and authToken parameters are required."}), 400
	
	conn = get_db()
	cursor = conn.cursor()

	cursor.execute('SELECT * FROM orgs WHERE org = ? AND authToken = ?', (org, authToken))
	client = cursor.fetchone()

	if client is None:
		return jsonify({'error': 'organization not found or authentication failed'}), 404
	
	update_fields = []
	update_values = []

	if url:
		update_fields.append('url = ?')
		update_values.append(url)
	if bucket:
		update_fields.append('bucket = ?')
		update_values.append(bucket)
	if measurement:
		update_fields.append('measurement = ?')
		update_values.append(measurement)
	if field:
		update_fields.append('field = ?')
		update_values.append(field)

	update_values.append(org)
	update_values.append(authToken)

	if update_fields:
		update_query = f'UPDATE orgs SET {", ".join(update_fields)} WHERE org = ? AND authToken = ?'
		cursor.execute(update_query, update_values)
		conn.commit()

	conn.close()

	return jsonify({"message": "User updated successfully"}), 200

	
@app.route('/updateData', methods=['PUT'])
def updateData():

	org = request.args.get('org')
	authToken = request.args.get("authToken")
	token = request.args.get('token')

	if not org or not authToken:
		return jsonify({"error": "org and authToken parameters are required."}), 400

	conn = get_db()
	cursor = conn.cursor()

	cursor.execute('SELECT * FROM orgs WHERE org = ? AND authToken = ?', (org, authToken))
	client = cursor.fetchone()

	if client is None:
		return jsonify({'error': 'organization not found or authentication failed'}), 404
	
	url = client[1]
	bucket = client[2]
	measurement = client[3]
	field = client[4]

	try:
		client = InfluxDBClient(url=url, token=token, org=org, timeout=60000)

		buckets_api = client.buckets_api()
		if not buckets_api.find_bucket_by_name(bucket):
			buckets_api.create_bucket(bucket_name=bucket, org=org)

		query_api = client.query_api()

		# Flux query to fetch the last timestamp from the specified measurement
		query =f'''
				from(bucket: "{bucket}")
					|> range(start: -1y)
					|> filter(fn: (r) => r._measurement == "{measurement}")
					|> last()
					|> keep(columns: ["_time"])
				'''
		
		date_obj = None	
		result = query_api.query(org=org, query=query)
		for table in result:
				for record in table.records:
					datetime_obj = record.get_time()
					if datetime_obj:
						date_obj = datetime_obj.date()

		if not date_obj:
			date_obj = datetime(2017,1,1).date()

		URL = "https://precoscombustiveis.dgeg.gov.pt/api/PrecoComb/PMD"

		dataIni = date_obj.strftime('%Y-%m-%d')
		dataFim = datetime.today().date()
		nDias = date_obj - dataFim

		PARAMS = {'idsTiposComb':'3201', 'dataIni':dataIni, 'dataFim':dataFim,'qtdPorPagina':nDias,'pagina':'1', 'orderAsc':'1'}
		
		page = requests.get(url=URL,params=PARAMS)

		results = page.json()

		write_api = client.write_api(write_options=SYNCHRONOUS)
		points = []
		for dia in results['resultado']:
			number = float(dia['PrecoMedio'][:-2].replace(',', '.'))
			point = Point(measurement)\
				.field(field, number)\
				.time(dia['Data'], WritePrecision.NS)
			points.append(point)

		write_api.write(bucket=bucket, org=org, record=points)
		client.close()

		return jsonify({"message": "result"}), 200

	except Exception as e:
		print(f"Error: {e}")
		return jsonify({'error': str(e)}), 500
	
@app.route('/resetDB', methods=['GET'])
def resetDB():
	try:
		conn = get_db()
		cursor = conn.cursor()
		cursor.execute('DROP TABLE IF EXISTS orgs')
		create_table()
		conn.commit()
		conn.close()
		return jsonify({"message": "Database reset successfully"}), 200
	except Exception as e:
		print(f"Error resetting database: {e}")
		return jsonify({"error": str(e)}), 500


# internal function
def updateData(org, token, url, bucket, measurement, field):

	client = InfluxDBClient(url=url, token=token, org=org, timeout=60000)

	buckets_api = client.buckets_api()
	if not buckets_api.find_bucket_by_name(bucket):
		buckets_api.create_bucket(bucket_name=bucket, org=org)

	query_api = client.query_api()

	# Flux query to fetch the last timestamp from the specified measurement
	query =f'''
			from(bucket: "{bucket}")
				|> range(start: -1y)
				|> filter(fn: (r) => r._measurement == "{measurement}")
				|> last()
				|> keep(columns: ["_time"])
			'''
	
	date_obj = None	
	result = query_api.query(org=org, query=query)
	for table in result:
			for record in table.records:
				datetime_obj = record.get_time()
				if datetime_obj:
					date_obj = datetime_obj.date()

	if not date_obj:
		date_obj = datetime(2017,1,1).date()

	URL = "https://precoscombustiveis.dgeg.gov.pt/api/PrecoComb/PMD"

	dataIni = date_obj.strftime('%Y-%m-%d')
	dataFim = datetime.today().date()
	nDias = date_obj - dataFim

	PARAMS = {'idsTiposComb':'3201', 'dataIni':dataIni, 'dataFim':dataFim,'qtdPorPagina':nDias,'pagina':'1', 'orderAsc':'1'}
	
	page = requests.get(url=URL,params=PARAMS)

	results = page.json()

	write_api = client.write_api(write_options=SYNCHRONOUS)
	points = []
	for dia in results['resultado']:
		number = float(dia['PrecoMedio'][:-2].replace(',', '.'))
		point = Point(measurement)\
			.field(field, number)\
			.time(dia['Data'], WritePrecision.NS)
		points.append(point)

	write_api.write(bucket=bucket, org=org, record=points)
	client.close()


if __name__ == '__main__':
	create_table()
	app.run(debug=True)