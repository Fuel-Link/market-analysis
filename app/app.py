from flask import Flask, render_template, request, jsonify
from datetime import datetime
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS
from prophet import Prophet
import pandas as pd
import os

app = Flask(__name__)

INFLUXDB_URL = os.getenv('INFLUXDB_URL')
INFLUXDB_TOKEN = os.getenv('INFLUXDB_TOKEN')
INFLUXDB_ORG = os.getenv('INFLUXDB_ORG')

# print(f"URL: {INFLUXDB_URL}, Token: {INFLUXDB_TOKEN}, Org: {INFLUXDB_ORG}")


@app.route('/')
def home():
	# Render an HTML page with a button
	return render_template('index.html')


@app.route('/predict', methods=["GET"])
def predict():
	
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


@app.route('/data')
def data():

	write_client = InfluxDBClient(url=INFLUXDB_URL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG)
	write_api = write_client.write_api(write_options=SYNCHRONOUS)

	date = request.args.get("date")
	price = request.args.get("price")

	if not date or not price:
		return jsonify({"error": "Date and price parameters are required."}), 400

	# date_str = date  # Example date string
	date_obj = datetime.strptime(date, '%Y-%m-%d')
	point = Point("Prices")\
		.field("y", float(price))\
		.time(date_obj, WritePrecision.NS)

	write_api.write(bucket="Gas-Prices", org=INFLUXDB_ORG, record=point)
	write_client.close()
	
	return jsonify({"message": "Data submitted successfully"}), 200

if __name__ == '__main__':
	app.run(debug=True)