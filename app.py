from flask import Flask, render_template, request, jsonify
import influxdb_client, os, time
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS
from prophet import Prophet
import pandas as pd

app = Flask(__name__)

token = "UNVypEIb7GeCNRuz2wwzIHynU8b0gTrrrb73KIdf5FGr0r2gO7i1gfYm5x3wzuo4rOgbOJ-zyKovI4VLSWMr3Q=="
org = "Gas-pump"
url = "http://localhost:8086"

client = influxdb_client.InfluxDBClient(url=url, token=token, org=org)

@app.route('/')
def home():
	# Render an HTML page with a button
	return render_template('index.html')


@app.route('/predict')
def predict():

	measurement = request.args.get('measurement')
	field = request.args.get('field')

	if not measurement or not field:
		return jsonify({'error': 'Measurement and field parameters are required'}), 400

	# Construct the Flux query
	query = f'''
	from(bucket: "{"Gas-Prices"}")
		|> range(start: 0)
		|> filter(fn: (r) => r._measurement == "{measurement}" and r._field == "{field}")
	'''
	#"Prices" and r._field == "y"

	# Query InfluxDB
	result = client.query_api().query_data_frame(query=query, org=org)
	if result.empty:
		return jsonify({'error': 'No data found for the specified date range'}), 404

	print(result)
	# Prepare DataFrame for Prophet
	df = result.rename(columns={"_time": "ds", "_value": "y"})

	df['ds'] = df['ds'].dt.tz_localize(None)

	m = Prophet()
	m.fit(df)

	future = m.make_future_dataframe(periods=15)
	future.tail()

	forecast = m.predict(future)


	predictions = forecast[['ds', 'yhat']].tail(15)
	predictions_list = predictions.to_dict('records')

	return jsonify({'predictions': predictions_list})

if __name__ == '__main__':
	app.run(debug=True)