# coded by Awnish Ranjan : ranjanawnish07@gmail.com

import os
import json
import smtplib
import requests
import sqlite3
import time
import schedule
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from dotenv import load_dotenv

# Load configurations from .env file
load_dotenv()

API_KEY = os.getenv("API_KEY")
ALERT_THRESHOLD_TEMP = float(os.getenv("ALERT_THRESHOLD_TEMP"))
ALERT_THRESHOLD_CONSECUTIVE_UPDATES = int(os.getenv("ALERT_THRESHOLD_CONSECUTIVE_UPDATES"))
TEMP_SCALE = os.getenv("TEMP_SCALE")
FETCH_INTERVAL = int(os.getenv("FETCH_INTERVAL"))
CITIES = json.loads(os.getenv("CITIES"))
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
ALERT_RECIPIENTS = os.getenv("ALERT_RECIPIENTS")

# Fetch weather data from OpenWeatherMap
def fetch_weather_data(city_name, lat, lon):
    url = f"http://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={API_KEY}"
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching data for {city_name}: {e}")
        return None

# Convert temperature from Kelvin to Celsius
def kelvin_to_celsius(temp_kelvin):
    return temp_kelvin - 273.15

# Convert temperature from Kelvin to Fahrenheit
def kelvin_to_fahrenheit(temp_kelvin):
    return (temp_kelvin - 273.15) * 9/5 + 32

# Convert temperature from Kelvin to the user preferred scale
def convert_temperature(temp_kelvin):
    if TEMP_SCALE == "Celsius":
        return kelvin_to_celsius(temp_kelvin)
    elif TEMP_SCALE == "Fahrenheit":
        return kelvin_to_fahrenheit(temp_kelvin)
    return temp_kelvin

# Setup SQLite Database
def setup_database():
    try:
        conn = sqlite3.connect("weather_data.db")
        cursor = conn.cursor()
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS weather_data (
            city TEXT,
            date TEXT,
            temp REAL,
            feels_like REAL,
            weather_condition TEXT,
            timestamp INTEGER
        )
        ''')
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS daily_summary (
            city TEXT,
            date TEXT,
            avg_temp REAL,
            max_temp REAL,
            min_temp REAL,
            dominant_condition TEXT,
            PRIMARY KEY (city, date)
        )
        ''')
        conn.commit()
    except sqlite3.Error as e:
        print(f"Error setting up database: {e}")
    finally:
        if conn:
            conn.close()

# Insert weather data into database
def insert_weather_data(city, weather_data):
    temp = weather_data['main']['temp']
    feels_like = weather_data['main']['feels_like']
    weather_condition = weather_data['weather'][0]['main']
    timestamp = weather_data['dt']
    
    try:
        conn = sqlite3.connect("weather_data.db")
        cursor = conn.cursor()
        
        # Get the current date for daily summary purposes
        current_date = datetime.utcfromtimestamp(timestamp).strftime('%Y-%m-%d')
        
        cursor.execute('''
        INSERT INTO weather_data (city, date, temp, feels_like, weather_condition, timestamp)
        VALUES (?, ?, ?, ?, ?, ?)
        ''', (city, current_date, temp, feels_like, weather_condition, timestamp))
        
        conn.commit()
    except sqlite3.Error as e:
        print(f"Error inserting data for {city}: {e}")
    finally:
        if conn:
            conn.close()

# Generate daily rollups and display summary
def generate_daily_summary():
    try:
        conn = sqlite3.connect("weather_data.db")
        cursor = conn.cursor()

        # Fetch weather data grouped by city and date with the most frequent weather condition
        cursor.execute('''
        SELECT city, date, AVG(temp) as avg_temp, MAX(temp) as max_temp, MIN(temp) as min_temp, weather_condition
        FROM (
            SELECT city, date, temp, weather_condition, COUNT(weather_condition) OVER (PARTITION BY city, date, weather_condition) as weather_condition_count
            FROM weather_data
        ) 
        WHERE weather_condition_count = (
            SELECT MAX(weather_condition_count)
            FROM (
                SELECT COUNT(weather_condition) as weather_condition_count
                FROM weather_data wd
                WHERE wd.city = city AND wd.date = date
                GROUP BY wd.weather_condition
            )
        )
        GROUP BY city, date
        ''')

        rows = cursor.fetchall()

        # Process summaries for each city
        for row in rows:
            city, date, avg_temp, max_temp, min_temp, dominant_condition = row[:6]

            # Check if a daily summary for the city and date already exists
            cursor.execute('''
            SELECT 1 FROM daily_summary WHERE city = ? AND date = ?
            ''', (city, date))
            exists = cursor.fetchone()

            if exists:
                # Update existing summary
                cursor.execute('''
                UPDATE daily_summary SET avg_temp = ?, max_temp = ?, min_temp = ?, dominant_condition = ?
                WHERE city = ? AND date = ?
                ''', (avg_temp, max_temp, min_temp, dominant_condition, city, date))
            else:
                # Insert new summary
                cursor.execute('''
                INSERT INTO daily_summary (city, date, avg_temp, max_temp, min_temp, dominant_condition)
                VALUES (?, ?, ?, ?, ?, ?)
                ''', (city, date, avg_temp, max_temp, min_temp, dominant_condition))

            # Convert temperatures to user preferred scale for display
            avg_temp_display = convert_temperature(avg_temp)
            max_temp_display = convert_temperature(max_temp)
            min_temp_display = convert_temperature(min_temp)

            # Display the daily summary in the console
            print(f"City: {city}, Date: {date}, Avg Temp: {avg_temp_display:.2f} {TEMP_SCALE}, Max Temp: {max_temp_display:.2f} {TEMP_SCALE}, Min Temp: {min_temp_display:.2f} {TEMP_SCALE}, Weather: {dominant_condition}")

        conn.commit()
    except sqlite3.Error as e:
        print(f"Error generating daily summary: {e}")
    finally:
        if conn:
            conn.close()

# Send email alert
def send_email_alert(city, temp):
    subject = f"Weather Alert for {city}"
    body = f"The temperature in {city} has exceeded {ALERT_THRESHOLD_TEMP:.2f} {TEMP_SCALE}."
    
    msg = MIMEMultipart()
    msg['From'] = EMAIL_ADDRESS
    msg['To'] = ALERT_RECIPIENTS
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))
    
    try:
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            text = msg.as_string()
            server.sendmail(EMAIL_ADDRESS, ALERT_RECIPIENTS, text)
            print(f"Alert email sent to {ALERT_RECIPIENTS} for {city}")
    except smtplib.SMTPException as e:
        print(f"Error sending email alert for {city}: {e}")

alert_cache = {}

def check_for_alerts(city, temp):
    global alert_cache
    
    # If temperature exceeds threshold, increment counter
    if temp > ALERT_THRESHOLD_TEMP:
        alert_cache[city] = alert_cache.get(city, 0) + 1
        if alert_cache[city] >= ALERT_THRESHOLD_CONSECUTIVE_UPDATES:
            print(f"ALERT: {city} has crossed {ALERT_THRESHOLD_TEMP:.2f} {TEMP_SCALE} for {ALERT_THRESHOLD_CONSECUTIVE_UPDATES} consecutive updates!")
            send_email_alert(city, temp)
    else:
        alert_cache[city] = 0  # Reset if below threshold

# Task to fetch data and process it
def weather_monitoring_task():
    for city, coords in CITIES.items():
        weather_data = fetch_weather_data(city, coords['lat'], coords['lon'])
        if weather_data:
            insert_weather_data(city, weather_data)
            temp = weather_data['main']['temp']
            
            # Convert temperatures to user preferred scale for display
            temp_display = convert_temperature(temp)
            feels_like_display = convert_temperature(weather_data['main']['feels_like'])
            
            # Display current weather data in the console
            print(f"Current Weather in {city}: Temp: {temp_display:.2f} {TEMP_SCALE}, Feels Like: {feels_like_display:.2f} {TEMP_SCALE}, Condition: {weather_data['weather'][0]['main']}")
            
            check_for_alerts(city, temp)
    
    generate_daily_summary()

# Schedule the job
schedule.every(FETCH_INTERVAL).minutes.do(weather_monitoring_task)

if __name__ == "__main__":
    setup_database()
    while True:
        schedule.run_pending()
        time.sleep(1)
