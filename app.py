from flask import Flask, request, jsonify
from analysis import get_prediction

app = Flask(__name__)

@app.route('/predict')
def predict():

    prediction_date,predicted_value = get_prediction(15)

    return jsonify({'date': prediction_date, 'predicted_value': predicted_value})

if __name__ == '__main__':
    app.run(debug=True)