from collections.abc import Callable
from baserowapi import Baserow, Filter
import logging
import sys
from typing import Callable, List

logger = logging.getLogger(__name__)

def _compute_id_control_digit(id_num):
    """Computes the remainder of the check_digit of the id. If valid, the return value is 0."""
    id_num = id_num.zfill(9)
    assert isinstance(id_num, str) and len(id_num) == 9 and id_num.isnumeric()

    total = 0
    for i in range(9):
        val = int(id_num[i]) # converts char to int
        if i%2 == 0:        # even index (0,2,4,6,8)
            total += val
        else:               # odd index (1,3,5,7,9)
            if val < 5:
                total += 2*val
            else:
                total += ((2*val)%10) + 1 # sum of digits in 2*val
                                          # 'tens' digit must be 1
    total = total%10            # 'ones' (rightmost) digit
    check_digit = (10-total)%10 # the complement modulo 10 of total
                                # for example 42->8, 30->0
    return check_digit

class BaserowAutomations:
    def __init__(self, baserow_token, activists_table_id, event_reg_table_id,
                 recruitment_table_id):
        self.baserow = Baserow(url='https://api.baserow.io', token=baserow_token)
        self.table_activists = self.baserow.get_table(activists_table_id)
        self.table_event_registration = self.baserow.get_table(event_reg_table_id)
        self.recruitment_table = self.baserow.get_table(recruitment_table_id)

    def update_row_safe(self, row):
        try:
            row.update()
        except Exception as e:
            print(e)

    def get_all_activists(self): 
        return self.table_activists.get_rows()

    def get_all_team_recruitments(self):
        return self.recruitment_table.get_rows()

    def get_all_registrations(self): 
        return self.table_event_registration.get_rows()

    def validate_ids(self):
        table = self.table_activists
        id_not_checked_filter = Filter('ת"ז תקינה', '', 'empty')
        id_exists_filter = Filter('ת.ז', '', 'not_empty')
        rows = table.get_rows(filters=[id_not_checked_filter, id_exists_filter])

        for row in rows:
            logger.info(f"{row['שם מלא']}")
            id_num = row['ת.ז']
            try:
                id_validation = _compute_id_control_digit(id_num)
            except AssertionError:
                logger.error(f'Assertion error with {row["שם מלא"]}, {row["ת.ז"]}')
                continue
        
            if id_validation != 0:
                logger.info(f"{row['שם מלא']}, ID remaining={id_validation}")
                row['ת"ז תקינה'] = 'לא'
            else:
                logger.info(f'{row["שם מלא"]} has a valid ID')
                row['ת"ז תקינה'] = 'כן'
            
            self.update_row_safe(row)

    def _build_phone_to_field_dict_from_table_rows(self, field_name, table_rows):
        """Gets a field name and table rows. Finds a field whose name contains 
        field_name (there should be a single one of these), and returns a dict
        from (normalized) phone numbers to the corresponding field values."""
        phone_to_field = {}

        for row in table_rows:
            # Find the column name that contains field_name. Written like that in
            # case the name will be drafted one day, to stay as general as possible
            field_full_name = [k for k in row.fields if field_name in k]
            if not field_full_name:
                raise KeyError(f"Can't find a key that contains {field_name}"
                                f"on the registrations table")
            elif len(field_full_name) > 1:
                raise KeyError(f"Too many columns with a name that contains {field_name}")
            field_full_name = field_full_name[0]

            # Store the field content
            field_content = row[field_full_name]

            phone_num = row['_NormalizedPhoneNumber']

            if field_content:
                if phone_num in phone_to_field:
                    phone_to_field[phone_num].append(field_content)
                else:
                    phone_to_field[phone_num] = [field_content]

        return phone_to_field

    def _add_to_dict_if_not_empty(self, key, values, dic):
        """Appends values (a list or a tuple. Will be converted to a list of it's not) to dic[key],
        which should be a list.
        If key isn't in dic, the list will be created."""
        if not isinstance(values, (list, tuple)):
            values = [values]
        if values:
            if key not in dic:
                dic[key] = []
            dic[key].extend(values)

    def _fill_field_from_registration_to_activists(self, registration_field: str,
            activists_field: str, full_run: bool = False,
            additional_query_function: Callable = None):
        """Fills the field activists_field in the activists table from the field
        registration_Field in the registration table, based on (normalized)
        phone numbers matching. If additional_query_function is supplied, it's
        being called with the (normalized) phone number, and its results too
        will be added to the activists_field. the activists table is update and
        data is appended, not overwritten. Duplicate values will be cleared though.

        Args:
            * registration_field - the field to be queried from the registration
            table.
            * activists_field - the field to be updated in the activists table
            * full_run - if False, only rows with empty activists_field will
            be processed.
            activists table.
            * additional_query_function - if supplied, will be called with the 
            normalized phone number to query for more data to be appended to the
            activists_field."""
        registration_rows = self.table_event_registration.get_rows()
        phone_to_field_dict = self._build_phone_to_field_dict_from_table_rows(
            registration_field, registration_rows)

        phone_filter = Filter('_NormalizedPhoneNumber', '', 'not_empty')
        empty_field_filter = Filter(activists_field, '', 'empty')
        filters = [phone_filter] if full_run else [phone_filter, empty_field_filter]
        activists_rows = self.table_activists.get_rows(filters=filters)
        for row in activists_rows:
            phone = row['_NormalizedPhoneNumber']
            # add the phone's queried data from the additional query function
            if additional_query_function:
                queried_values = additional_query_function(phone)
                self._add_to_dict_if_not_empty(phone, queried_values, phone_to_field_dict)
            
            # add the current field content, if any
            if row[activists_field]:
                self._add_to_dict_if_not_empty(phone, row[activists_field].split(' , '),
                                               phone_to_field_dict)
            
            # clear duplicates
            if phone in phone_to_field_dict:
                phone_to_field_dict[phone] = list(set([url.strip() for url in phone_to_field_dict[phone] if url]))
            
            if phone in phone_to_field_dict and phone_to_field_dict[phone]:    
                # update the row
                logging.warning(f'About to update {row["שם מלא"]} with {" , ".join(phone_to_field_dict[phone])}')
                row[activists_field] = ' , '.join(phone_to_field_dict[phone])
                self.update_row_safe(row)
                logging.warning(f'Updated {row["שם מלא"]}')

    def fill_facebook_from_registration_to_activist(self, phone2fb_db=None, full_run=False):
        """Fills the facebook profile at the activists table from the registrations table. Searches by the phone number.
        If phone2fb_db is supplied, e.g. from the leaked FB database, it fills from it as well.
        The DB should be an sqlite with a table named Facebook and columns 'phone' and 'uid'.
        If full_run is False, only rows with no filled facebook profile will be processed."""
        
        def query_fb_by_phone(phone_number): return phone2fb_db.query(phone_number=phone_number)
        self._fill_field_from_registration_to_activists('פייסבוק', 'פייסבוק',
                                                        full_run,
                                                        query_fb_by_phone)

    def fill_emails_from_registration_to_activist(self, full_run: bool=False):
        """Fills the email addresses from the registrations table to the
        activists table. If full_run == False, only rows with empty email field
        in activists will be filled."""
        self._fill_field_from_registration_to_activists('דואר אלקטרוני',
                                                        'email', full_run)      

    def fill_name_by_id(self, rishumon_query_engine=None,
                        elector_query_engine=None):
        has_id_filter = Filter('ת.ז', '', 'not_empty')
        filters = [has_id_filter]
        non_empty_rishumon_name_filter = Filter('שם רישומון', '', 'empty')
        non_empty_elector_name_filter = Filter('שם אלקטור', '', 'empty')
        if rishumon_query_engine and not elector_query_engine:
            filters.append(non_empty_rishumon_name_filter)
        elif not rishumon_query_engine and elector_query_engine:
            filters.append(non_empty_elector_name_filter)
        elif not rishumon_query_engine and not elector_query_engine:
            return
        
        rows = self.table_activists.get_rows(filters=filters)
        for row in rows:
            ID = row['ת.ז']

            # if ID is invalid, skip.
            # A hacky solution since I failed to use a filter on ת"ז תקינה
            try:
                if _compute_id_control_digit(ID) != 0:
                    continue
            except AssertionError:
                continue
            
            for engine, field_name, first_name_field, last_name_field in (
                (rishumon_query_engine, 'שם רישומון', 'Name', 'Family'),
                (elector_query_engine, 'שם אלקטור', 'first_name', 'last_name')
            ):
                if engine:
                    query_results = engine.query(ID=ID)
                    if query_results:
                        row[field_name] = f'{query_results[0][first_name_field]} {query_results[0][last_name_field]}'
                    else:
                        row[field_name] = 'NOT FOUND'
                    
                    self.update_row_safe(row)

    def fill_birthday_by_id(self, rishumon_query_engine):
        rishumon_name_found_filter = Filter('שם רישומון', 'NOT FOUND', 'not_equal')
        # filter only valid IDs. The id for 'כן' was taken from
        # https://baserow.io/api-docs/database/115460
        valid_id_filter = Filter('ת"ז תקינה', 1995985, 'single_select_equal')
        filters = [rishumon_name_found_filter, valid_id_filter]

        rows = self.table_activists.get_rows(filters=filters)
        for row in rows:
            ID = row['ת.ז']
            query_results = rishumon_query_engine.query(ID=ID)
            if query_results:
                bd = query_results[0]['BDate']
                row['ת. לידה רישומון'] = f'{bd[0:4]}-{bd[4:6]}-{bd[6:8]}'
                
                self.update_row_safe(row)
    
    def link_activists_and_recruitments(self):
        """Updates in the classification table whether one is a candidate for
        recruitment, and links their classification status to the recruitment
        table."""
        recruitment_rows = self.recruitment_table.get_rows()
        recruitment_phones = {r['טלפון'].strip(): i for i, r in enumerate(recruitment_rows)}

        phone_filter = Filter('_NormalizedPhoneNumber', '', 'not_empty')
        activists_rows = self.table_activists.get_rows(filters=[phone_filter])
        for r in activists_rows:
            phone = r['_NormalizedPhoneNumber']
            if phone in recruitment_phones:
                r['מועמד.ת לצוות'] = 'כן'
                recruitment_row = recruitment_rows[recruitment_phones[phone]]
                recruitment_row['פעילי שטח'] = [r.id]
                recruitment_row.update()
            else:
                r['מועמד.ת לצוות'] = 'לא'
            
            self.update_row_safe(r)

    def get_activists_to_save_as_contact(self):
        table = self.baserow.get_table(self.table_activists)
        phone_filter = Filter('טלפון', '','not_empty')
        phone2_filter = Filter('שמור כאיש קשר', 'False', 'equal')
        
        classification_filter = Filter('האם עבר סיווג', 'נקי - ', 'contains')
        rows = self.table_activists.get_rows(filters=[phone_filter, phone2_filter, classification_filter])

        contacts_to_save = []

        for row in rows:
            name = f"{row['שם מלא']} משנים כיוון ({row['UUID']})"
            number = f"{row['_NormalizedPhoneNumber']}"
            uuid = f"{row['UUID']}"

            contacts_to_save.append(contact(name, number, uuid))
            
        return contacts_to_save

    def update_saved_contact(self, uuid):
        row_to_update = self.table_activists.get_row(uuid)
        row_to_update['שמור כאיש קשר'] = True
        
        self.update_row_safe(row_to_update)

    @staticmethod
    def find_duplicates(rows, name_field):
        """Finds duplicates based on the (normalized) phone number and return as
        {'phone_number': [name1, name2, ...]}
        args:
            rows - to rows to process
            name_field - the name of the field of names"""
        phones_to_names = {}
        for row in rows:
            phone = row['_NormalizedPhoneNumber']
            name = row[name_field]
            if phone not in phones_to_names:
                phones_to_names[phone] = []
            phones_to_names[phone].append(name)
        
        keys_to_delete = []
        for phone in phones_to_names:
            if len(phones_to_names[phone]) < 2:
                keys_to_delete.append(phone)
        for phone in keys_to_delete:
            del phones_to_names[phone]
        
        return phones_to_names

    def find_duplicates_in_activists(self):
        return self.find_duplicates(self.table_activists.get_rows(), 'שם מלא')

    def find_duplicates_in_registrations(self):
        return self.find_duplicates(self.table_event_registration.get_rows(), 'שם מלא')
