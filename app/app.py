import os
import json
import sqlite3
import requests
import binascii
import pandas as pd
from prophet import Prophet
from datetime import datetime, timedelta
from influxdb_client.client.write_api import SYNCHRONOUS
from flask import Flask, render_template, request, jsonify
from influxdb_client import InfluxDBClient, Point, WritePrecision

app = Flask(__name__)

DATABASE = '/app/data/orgs.db'

def get_db():
	conn = sqlite3.connect(DATABASE)
	conn.execute('PRAGMA foreign_keys = ON')
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
	create_table()
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
		read_client = InfluxDBClient(url=url, token=token, org=org, verify_ssl=False, timeout=60000)
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

		decision = assess_fuel(1,predictions_list)

		return jsonify({'predictions': predictions_list, 'real': actual_values, 'decision': decision}), 200

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
		client = InfluxDBClient(url=url, token=token, org=org, verify_ssl=False, timeout=60000)

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

		page = requests.get(url=URL,params=PARAMS, verify=False)

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
		cursor.execute('DROP TABLE IF EXISTS fuel_usage')
		cursor.execute('DROP TABLE IF EXISTS fuel_restock')
		create_table()
		conn.commit()
		conn.close()
		return jsonify({"message": "Database reset successfully"}), 200
	except Exception as e:
		print(f"Error resetting database: {e}")
		return jsonify({"error": str(e)}), 500

@app.route('/usePump', methods=['POST'])
def use_pump():
	data = request.get_json()
	pump_id = data.get('pump_id')
	amount = data.get('amount')
	org = data.get('org')
	client = data.get('client')

	if not pump_id or amount is None or not client or not org:
		return jsonify({"error": "pump_id, amount, client and org are required", "values":(pump_id, amount, client, org)}), 400

	conn = sqlite3.connect(DATABASE)
	cursor = conn.cursor()
	cursor.execute('INSERT INTO fuel_usage (pump_id, amount, client, timestamp, org) VALUES (?, ?, ?, ?, ?)', (pump_id, amount, client, datetime.now(), org))
	conn.commit()
	conn.close()
	return jsonify({"message": "Pump usage recorded successfully"}), 200

@app.route('/restockFuel', methods=['POST'])
def restock_fuel():
	data = request.get_json()
	pump_id = data.get('pump_id')
	amount = data.get('amount')
	org = data.get('org')

	if not pump_id or amount is None or not org:
		return jsonify({"error": "pump_id, amount and org are required", "values":(pump_id, amount, org)}), 400

	conn = sqlite3.connect(DATABASE)
	cursor = conn.cursor()
	cursor.execute('INSERT INTO fuel_restock (pump_id, amount, timestamp, org) VALUES (?, ?, ?, ?)', (pump_id, amount, datetime.now(), org))
	conn.commit()
	conn.close()
	return jsonify({"message": "Fuel restocked successfully"}), 200

def assess_fuel(pump_id, predictions):

	# Load fuel usage and restock data
	conn = sqlite3.connect(DATABASE)
	fuel_usage = pd.read_sql_query('SELECT * FROM fuel_usage WHERE pump_id = ?', conn, params=(pump_id,))
	fuel_restock = pd.read_sql_query('SELECT * FROM fuel_restock WHERE pump_id = ?', conn, params=(pump_id,))
	conn.close()

	total_used = fuel_usage['amount'].sum()
	total_restocked = fuel_restock['amount'].sum()
	current_stock = total_restocked - total_used

	fuel_usage['timestamp'] = pd.to_datetime(fuel_usage['timestamp'])
	daily_usage = fuel_usage.set_index('timestamp').resample('D').sum()
	avg_daily_consumption = daily_usage['amount'].mean()

	predictions_df = pd.DataFrame(predictions)
	predictions_df['ds'] = pd.to_datetime(predictions_df['ds'], format='%a, %d %b %Y %H:%M:%S GMT')

	# Predict future consumption
	decision = "Wait"
	days_ahead = 7
	predicted_consumption = avg_daily_consumption * days_ahead

	# Determine if we need to restock
	if current_stock < predicted_consumption:
		for i in range(days_ahead):
			future_date = datetime.now() + timedelta(days=i)
			future_date_str = future_date.strftime('%Y-%m-%d')

			# Get the predicted price for the future date
			future_price = predictions_df[predictions_df['ds'].dt.strftime('%Y-%m-%d') == future_date_str]['yhat'].values[0]

			# Calculate the future stock level
			future_stock = current_stock - (avg_daily_consumption * (i + 1))

			if future_stock < 1000:
				decision = "Buy Now"
				# Check if the price is expected to decrease before the stock falls below the margin
				for j in range(i + 1, days_ahead):
					later_date = datetime.now() + timedelta(days=j)
					later_date_str = later_date.strftime('%Y-%m-%d')
					later_price = predictions_df[predictions_df['ds'].dt.strftime('%Y-%m-%d') == later_date_str]['yhat'].values[0]

					if later_price < future_price:
						decision = "Wait"
						break

				break
	return decision

# internal function
def updateData(org, token, url, bucket, measurement, field):

	client = InfluxDBClient(url=url, token=token, org=org, verify_ssl=False, timeout=60000)

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

	page = requests.get(url=URL,params=PARAMS, verify=False)

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