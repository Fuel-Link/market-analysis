from flask import Flask, render_template, request, jsonify
from datetime import datetime
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS
from prophet import Prophet
from prophet.serialize import model_to_json, model_from_json
from datetime import datetime, timedelta, timezone
# import pandas as pd

app = Flask(__name__)

read_token = "hm-Il0Rq9lXQhmKR4-gnXTgjHiaJ92Qv8fZ2b3ga1DBP5gqf7f3V6DHsOYvpW_afnaCEmwbMefMCOZQV49y8Gw=="
write_token = "hm-Il0Rq9lXQhmKR4-gnXTgjHiaJ92Qv8fZ2b3ga1DBP5gqf7f3V6DHsOYvpW_afnaCEmwbMefMCOZQV49y8Gw=="
org = "FuelLink"
url = "http://localhost:8086"

read_client = InfluxDBClient(url=url, token=read_token, org=org)
write_client = InfluxDBClient(url=url, token=write_token, org=org)
write_api = write_client.write_api(write_options=SYNCHRONOUS)


@app.route('/')
def home():
	# Render an HTML page with a button
	return render_template('index.html')


@app.route('/predict')
def predict():

	bucket = request.args.get('bucket')
	measurement = request.args.get('measurement')
	field = request.args.get('field')

	if not measurement or not field:
		return jsonify({'error': 'Measurement and field parameters are required'}), 400

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
	df = result.rename(columns={"_time": "ds", "_value": "y"})

	df['ds'] = df['ds'].dt.tz_localize(None)

	m = Prophet()
	m.fit(df)

	future = m.make_future_dataframe(periods=15)
	future.tail()

	forecast = m.predict(future)


	predictions = forecast[['ds', 'yhat']].tail(15)
	predictions_list = predictions.to_dict('records')

	for prediction in predictions_list:
		print(prediction)
		# Parse the date and value
		date = prediction['ds']
		yhat = prediction['yhat']

		# Create a Point
		point = Point("Predictions")\
			.field("yhat", yhat)\
			.time(date, WritePrecision.NS)

		write_api.write(bucket='Predictions', org=org, record=point)

	query = '''
			from(bucket: "Predictions")
			|> range(start: now(), stop: 15d)
			|> filter(fn: (r) => r["_measurement"] == "Predictions")
			|> filter(fn: (r) => r["_field"] == "yhat")
			'''
	
	result = read_client.query_api().query(org=org, query=query)

	# Process the results
	for table in result:
		for record in table.records:
			print(f'Time: {record.get_time()}, Predicted Value: {record.get_value()}')



	return jsonify({'predictions': predictions_list})


@app.route('/data')
def data():

	date = request.args.get("date")
	price = request.args.get("price")

	if not date or not price:
		return jsonify({"error": "Date and price parameters are required."}), 400

	# date_str = date  # Example date string
	date_obj = datetime.strptime(date, '%Y-%m-%d')
	point = Point("Prices")\
		.field("y", float(price))\
		.time(date_obj, WritePrecision.NS)

	write_api.write(bucket="Gas-Prices", org=org, record=point)
	
	return jsonify({"message": "Data submitted successfully"}), 200

if __name__ == '__main__':
	app.run(debug=True)