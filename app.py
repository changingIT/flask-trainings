import logging
import sys
import os
import json
from datetime import datetime
from datetime import date
from dateutil.relativedelta import relativedelta

from BaserowAutomationsFile import BaserowAutomations       # type: ignore
from flask import Flask, send_file, render_template, url_for

"""
Flask routes
"""
app = Flask(__name__)
@app.route("/")
def index():
    training_dic = getTrainingParticipantCounts()
    return render_template('trainings.html', training_dic=training_dic)

"""
A function that gets the number of participants that are registered for each training
The data is fetched from Baserow
"""
def getTrainingParticipantCounts():
    baserowAccess = BaserowAutomations(
        baserow_token=os.environ.get('baserow_token'),
        activists_table_id=os.environ.get('activists_table_id'),
        event_reg_table_id=os.environ.get('event_registration_table_id'),
        recruitment_table_id=os.environ.get('recruitment_table_id')
    ) 

    registers = baserowAccess.get_all_registrations()
    training_dic = {}
    for register in registers:        
        submission_time_str = register["Submission Time"]
        # Assuming 'Submission Time' is in the format 2025-06-05T12:56:10.630Z
        pharsed_date = parse_date(submission_time_str)

        if pharsed_date is None:
            continue

        if pharsed_date.date() < date.today() - relativedelta(months=2):
            continue

        training = register["רישום לאירוע"]
        
        if training not in training_dic:
            training_dic[training] = 1
        else:
            training_dic[training] += 1

    return training_dic

    app.run(port=int(os.environ.get('PORT', 8080)))

"""
Helper functions
"""
def parse_date(date_str):
    date_formats = ["%m/%d/%Y %I:%M%p", "%Y-%m-%dT%H:%M:%S.%fZ", '%Y-%m-%dT%H:%M:%SZ']
    format_successful = False
    parsed_date = None

    for fmt in date_formats:
        try:
            parsed_date = datetime.strptime(date_str, fmt)
            format_successful = True
            break  # Exit the inner loop if parsing is successful
        except ValueError as ex:
            pass  # Try the next format if parsing fails

    if not format_successful:
        print("could not parse date " + date_str)
        return None
    
    return parsed_date

