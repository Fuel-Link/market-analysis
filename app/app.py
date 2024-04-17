import os
import json
import requests
import pandas as pd
from prophet import Prophet
from datetime import datetime
from influxdb_client.client.write_api import SYNCHRONOUS
from flask import Flask, render_template, request, jsonify
from influxdb_client import InfluxDBClient, Point, WritePrecision

app = Flask(__name__)

INFLUXDB_URL = os.getenv('INFLUXDB_URL')
INFLUXDB_TOKEN = os.getenv('INFLUXDB_TOKEN')
INFLUXDB_ORG = os.getenv('INFLUXDB_ORG')

Users = {}	

@app.route('/')
def home():
	# Render an HTML page with a button
	return render_template('index.html')

@app.route('/old/predict', methods=["GET"])
def OldPredict():
	
	read_client = InfluxDBClient(url=INFLUXDB_URL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG, timeout=60000)

	bucket = request.args.get('bucket')
	measurement = request.args.get('measurement')
	field = request.args.get('field')
	
	if not measurement or not field:
		return jsonify({'error': 'Measurement and field parameters are required'}), 400

	# If bucket does not exist, imports the Postos.csv into the database to run the model
	buckets_api = read_client.buckets_api()
	if not buckets_api.find_bucket_by_name(bucket):
		buckets_api.create_bucket(bucket_name=bucket, org=INFLUXDB_ORG)
		write_client = InfluxDBClient(url=INFLUXDB_URL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG, timeout=60000)
		write_api = write_client.write_api(write_options=SYNCHRONOUS)

		df = pd.read_csv('Postos.csv')

		points = []
		for index, row in df.iterrows():
			point = Point(measurement)\
				.field(field, float(row['y']))\
				.time(row['ds'], WritePrecision.NS)
			points.append(point)

		write_api.write(bucket=bucket, org=INFLUXDB_ORG, record=points)
		write_client.close()

	# Construct the Flux query
	query = f'''
	from(bucket: "{bucket}")
		|> range(start: 0)
		|> filter(fn: (r) => r._measurement == "{measurement}" and r._field == "{field}")
		|> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
	'''

	# Query InfluxDB
	result = read_client.query_api().query_data_frame(query=query, org=INFLUXDB_ORG)
	if result.empty:
		return jsonify({'error': 'No data found for the specified date range'}), 404

	# Prepare DataFrame for Prophet
	df = result.rename(columns={"_time": "ds", field: "y"})

	df['ds'] = df['ds'].dt.tz_localize(None)

	m = Prophet()
	m.fit(df)

	future = m.make_future_dataframe(periods=15)
	future.tail()

	forecast = m.predict(future)


	predictions = forecast[['ds', 'yhat']].tail(15)
	predictions_list = predictions.to_dict('records')

	read_client.close()
	return jsonify({'predictions': predictions_list})

@app.route('/predict', methods=["GET"])
def predict():
	
	org = request.args.get('org')
	token = request.args.get('token')
	days = request.args.get('days',default=15)

	if not org or not token:
		return jsonify({'error': 'org and token parameters are required'}), 400
	
	print(Users.get(org))
	
	if not Users.get(org):
		return jsonify({'error': 'organization not found'}), 404
	
	url= Users[org]["url"]
	bucket = Users[org]["bucket"]
	measurement = Users[org]["measurement"]
	field = Users[org]["field"]

	read_client = InfluxDBClient(url=url, token=token, org=org, timeout=60000)
	
	

	# If bucket does not exist, use the internal updateData function to create the bucket with all data
	buckets_api = read_client.buckets_api()
	if not buckets_api.find_bucket_by_name(bucket):
		updateData(org,token)

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
	return jsonify({'predictions': predictions_list, 'real':actual_values})


@app.route('/addClient', methods=['POST'])
def addClient():
	org = request.args.get("org")
	url = request.args.get("url")
	bucket = request.args.get("bucket")
	measurement = request.args.get("measurement")
	field = request.args.get("field")

	if not url or not org or not bucket or not measurement or not field:
		return jsonify({"error": "url, org, bucket, measurement and field parameters are required."}), 400

	newUser = {"url": url, "bucket": bucket, "measurement": measurement, "field": field}
	Users[org] = newUser

	return jsonify({"message": "User added successfully"}), 200


@app.route('/updateClient', methods=['PUT'])
def updateClient():
	org = request.args.get("org")
	url = request.args.get("url")
	bucket = request.args.get("bucket")
	measurement = request.args.get("measurement")
	field = request.args.get("field")

	if not org:
		return jsonify({"error": "org parameter is required."}), 400
	
	if not Users.get(org):
		return jsonify({'error': 'organization not found'}), 404
	
	if url:
		Users[org]['url'] = url
	if bucket:
		Users[org]['bucket'] = bucket
	if measurement:
		Users[org]['measurement'] = measurement
	if field:
		Users[org]['field'] = field

	return jsonify({"message": "User updated successfully"}), 200

	
@app.route('/updateData', methods=['PUT'])
def updateData():

	org = request.args.get('org')
	token = request.args.get('token')

	if not org or not token:
		return jsonify({'error': 'org and token parameters are required'}), 400
	
	if not Users.get(org):
		return jsonify({'error': 'organization not found'}), 404
	
	url= Users[org]["url"]
	bucket = Users[org]["bucket"]
	measurement = Users[org]["measurement"]
	field = Users[org]["field"]

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



# internal function
def updateData(org,token):

	url= Users[org]["url"]
	bucket = Users[org]["bucket"]
	measurement = Users[org]["measurement"]
	field = Users[org]["field"]

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
	app.run(debug=True)