# market-analysis for Fuel Link

To start the service run

```bash
docker compose up -d
```

The first step is to register the client in the service with /addClient, using the
- name of the organization, 
- influxdb url (if using the influxDB from this docker-compose: http://influxdb:8086), 
- name of the target bucket, 
- measurement name,
- field name,

like this:

```bash
curl -X POST "http://localhost:5000/addClient?org=OrgName&url=http://influxdb:8086&bucket=bucketName&measurement=measurementName&field=fieldName"
```

this will return a authentication token that is required for any other operation, these fields can be updated later with /updateClient, using the organization name and the authentication token, when updating all other parameters are optional

```bash
curl -X PUT "http://localhost:5000/updateClient?org=OrgName&authToken=yourAuthToken&url=newUrl&bucket=newBucket&measurement=newMeasurement&field=newField"
```


Predictions are calculated by calling /predict with a 
- organization name, 
- authToken, 
- token,
- optionally a number of days(default 15) 

like this:

```bash
curl -G "http://localhost:5000/predict" \
     --data-urlencode "org=OrgName" \
     --data-urlencode "authToken=yourAuthToken" \
     --data-urlencode "token=yourInfluxDBToken" \
     --data-urlencode "days=7"

```

this will query the db and calculate prediction values for the next days, those are returned like this aswell as the real values in the db:

```bash
{
    "predictions": [
        {
            "ds": "Wed, 03 Apr 2024 00:00:00 GMT",
            "yhat": 1.7213467119261394
        }
    ],
    "real": [
        {
            "ds": "Mon, 01 Apr 2024 00:00:00 GMT",
            "y": 1.7961
        }
    ]
}
```
Currently if the bucket that is select does not currently exist, it will be created and loaded with data by calling internally updateData.



The database can be updated by calling /updateData with the 
- organization name,
- authToken
- token,
  
like this:

```bash
curl -X PUT "http://localhost:5000/updateData?org=OrgName&authToken=yourAuthToken&token=yourInfluxDBToken"
```

This is will use the API https://precoscombustiveis.dgeg.gov.pt/api/PrecoComb/PMD, to fetch fuel prices.


The following endpoint will keep track of fuel consumption so that future use can be estimated.

```bash
curl -X POST "http://localhost:5001/usePump" \
     -H "Content-Type: application/json" \
     -d '{
           "pump_id": 2,
           "amount": 50.0,
	       "client "user123",
           "org": "Fuel-Link"
         }'
```


The following endpoint will keep track of when a pump is restocked.

```bash
curl -X POST "http://localhost:5001/restockFuel" \
     -H "Content-Type: application/json" \
     -d '{
           "pump_id": 1,
           "amount": 500.0,
           "org": "Fuel-Link"
         }'
```