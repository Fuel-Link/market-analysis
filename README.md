# market-analysis for Fuel Link

To start the service run

```bash
docker compose up -d
```

Currently access to influxdb is defined through the enviroment variables in docker-compose, if those change in the influxdb service they need to change here too.

Predictions are calculated by calling /predict with a bucket, measurement and field like this:

```bash
localhost:5000/predict?bucket=bucketName&measurement=measurementName&field=fieldName
```

this will query the db and calculate prediction values for the next 15 days, those are returned like this:

```bash
{
    "predictions": [
        {
            "ds": "Wed, 03 Apr 2024 00:00:00 GMT",
            "yhat": 1.7213467119261394
        }
    ]
}
```
Currently if the bucket that is select does not currently exist, it will be created and loaded with data from a .csv file. 
Also there is an example on how to use this in the home directory of this service