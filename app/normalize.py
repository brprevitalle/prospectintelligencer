import re

PROCESSING_VERSION = 'hudson-v1'
MISSING = {'', 'N/A', 'NULL', 'NONE', 'UNKNOWN'}


def clean(value):
    if value is None:
        return None
    value = re.sub(r'\s+', ' ', str(value)).strip().upper()
    return None if value in MISSING else value


def classify(raw):
    # Conservative Hudson-specific source descriptions. No inferred purchasing authority.
    description = clean(raw.get('USE_DESC')) or ''
    if 'CONDO' in description:
        return 'condominium', 'source use description; association responsibility unverified'
    if 'SINGLE FAMILY' in description:
        return 'single_family', 'source use description'
    if 'TWO FAMILY' in description or 'TWO-FAMILY' in description:
        return 'two_family', 'source use description'
    if 'THREE FAMILY' in description or 'THREE-FAMILY' in description:
        return 'small_multifamily', 'source use description'
    if 'APARTMENT' in description:
        return 'apartment', 'source use description; unit band requires review'
    if 'MIXED' in description:
        return 'mixed_use', 'source use description'
    # Local extended codes start with the Massachusetts three-digit use class.
    code = clean(raw.get('USE_CODE')) or ''
    if code.startswith('3'):
        return 'commercial_unclassified', 'use-code class 3; specific use needs review'
    if code.startswith('4'):
        return 'industrial_unclassified', 'use-code class 4; specific use needs review'
    return 'unknown', 'insufficient mapped source evidence'


def normalize(raw):
    issues = []
    parcel = clean(raw.get('LOC_ID'))
    assessment = clean(raw.get('PROP_ID'))
    address = clean(raw.get('SITE_ADDR'))
    owner = clean(raw.get('OWNER1'))
    mail_parts = [clean(raw.get(k)) for k in ('OWN_ADDR', 'OWN_CITY', 'OWN_STATE', 'OWN_ZIP')]
    mail = ', '.join(v for v in mail_parts if v) or None
    for value, issue in ((parcel, 'missing_parcel_identifier'), (assessment, 'missing_assessment_identifier'),
                         (address, 'missing_site_address'), (owner, 'missing_owner_name')):
        if not value:
            issues.append(issue)
    if not all(mail_parts):
        issues.append('incomplete_owner_mailing_address')
    segment, basis = classify(raw)
    if segment == 'unknown':
        issues.append('classification_needs_review')
    units = raw.get('UNITS')
    if not isinstance(units, int) or units <= 0:
        units = None
        issues.append('unit_count_unknown')
    if clean(raw.get('NO_MATCH')) == 'Y':
        issues.append('source_assessor_match_missing')
    return dict(parcel_key=parcel, assessment_key=assessment, address=address,
                owner_name=owner, owner_mail=mail, segment=segment,
                classification_basis=basis, units=units, use_code=clean(raw.get('USE_CODE')),
                issues=issues)
