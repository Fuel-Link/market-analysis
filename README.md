# market-analysis for Fuel Link

To start the service run

```bash
docker compose up -d
```

The first step is to register the client in the service with /addClient, using the
- name of the organization, 
- influxdb url, 
- name of the target bucket, 
- measurement name,
- field name,

like this:

```bash
http://localhost:5000/addClient?org=OrgName&url=Url&bucket=bucket&measurement=measurement&field=field
```
these fields can be updated later with /updateClient, using the organization name and all other parameters are optional

```bash
http://localhost:5000/updateClient?org=OrgName
```


Predictions are calculated by calling /predict with a 
- organization name, 
- token,
-  optionally a number os days(default 15) 

like this:

```bash
localhost:5000/predict?org=orgName&token=your_token_here&days=7
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
Currently if the bucket that is select does not currently exist, it will be created and loaded with data from a .csv file.



The database can be updated by calling /updateData with the 
- organization name,
- token,
  
like this:

```bash
localhost:5000/updateData?org=orgName&token=your_token_here
```

This is currently still using the csv to update the db, in the future it will use a web scraper to fetch the data.


 


Old method of calling predictions:

    Currently access to influxdb is defined through the enviroment variables in docker-compose, if those change in the influxdb service they need to change here too. If the influxdb is not running in docker then the INFLUXDB_URL needs to be changed 
    
    from 

    localhost:8086
    
    to 
    
    host.docker.internal:8086
    


    Predictions are calculated by calling /old/predict with a bucket, measurement and field like this:

    localhost:5000/old/predict?bucket=bucketName&measurement=measurementName&field=fieldName

    this will query the db and calculate prediction values for the next 15 days, those are returned like this:

    {
        "predictions": [
            {
                "ds": "Wed, 03 Apr 2024 00:00:00 GMT",
                "yhat": 1.7213467119261394
            }
        ]
    }