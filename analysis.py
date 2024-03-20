import pandas as pd
from prophet import Prophet


def get_prediction(days):
	df = pd.read_csv("Postos.csv")
	df.head()

	m = Prophet()
	m.fit(df)

	future = m.make_future_dataframe(periods=15)
	future.tail()

	forecast = m.predict(future)

	return forecast[['ds','yhat']].tail(days).to_numpy()
