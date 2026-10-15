from app.normalize import clean, normalize


def test_preserve_names_and_unknown_units():
    raw = {'OWNER1':'  ACME   LLC ', 'UNITS':0, 'USE_DESC':'Single Family Residential'}
    row = normalize(raw)
    assert row['owner_name'] == 'ACME LLC'
    assert raw['OWNER1'] == '  ACME   LLC '
    assert row['units'] is None
    assert row['segment'] == 'single_family'
    assert 'unit_count_unknown' in row['issues']


def test_condo_is_not_apartment_and_no_owner_inference():
    row = normalize({'USE_DESC':'Residential Condominium', 'UNITS':1})
    assert row['segment'] == 'condominium'
    assert row['owner_name'] is None
    assert 'missing_owner_name' in row['issues']


def test_missing_does_not_invent_contact_or_classification():
    assert clean(' N/A ') is None
    row = normalize({})
    assert row['segment'] == 'unknown'
    assert 'incomplete_owner_mailing_address' in row['issues']
    assert 'email' not in row
