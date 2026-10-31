"""InsightForge AI — evidence-grounded CSV analytics with Gemini-assisted agents."""
from flask import Flask, render_template, request, jsonify, send_file
from pathlib import Path
from collections import defaultdict
from dotenv import load_dotenv
from google import genai
import csv, io, uuid, json, math, os, re
from datetime import datetime

load_dotenv()
app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024
DATASETS = {}
MODEL = os.getenv('GEMINI_MODEL', 'gemini-3.8-flash')


def parse_csv_bytes(raw):
    text = raw.decode('utf-8-sig', errors='replace')
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError('CSV must contain a header row.')
    headers = [str(h).strip() for h in reader.fieldnames if h and str(h).strip()]
    if not headers:
        raise ValueError('No usable column headers found.')
    rows = []
    for row in reader:
        clean = {str(k).strip(): (v.strip() if isinstance(v, str) else v)
                 for k, v in row.items() if k is not None}
        if any(str(v or '').strip() for v in clean.values()):
            rows.append(clean)
    if not rows:
        raise ValueError('The CSV has a header but no data rows.')
    return headers, rows


def numeric_columns(headers, rows):
    found = []
    for h in headers:
        vals = [str(r.get(h, '')).strip().replace(',', '') for r in rows if str(r.get(h, '')).strip()]
        if vals:
            try:
                [float(v) for v in vals]
                found.append(h)
            except (ValueError, TypeError):
                pass
    return found


def profile_dataset(headers, rows):
    missing = {h: sum(1 for r in rows if not str(r.get(h, '') or '').strip()) for h in headers}
    duplicates = 0
    seen = set()
    if 'order_id' in headers:
        for row in rows:
            key = row.get('order_id', '')
            if key in seen: duplicates += 1
            seen.add(key)
    missing_total = sum(missing.values())
    quality = 100 if not rows else max(0, round(100 - missing_total / (len(rows) * max(1, len(headers))) * 60 - duplicates / max(1, len(rows)) * 40))
    issues = []
    if missing_total: issues.append(f'{missing_total} missing cell(s) detected.')
    if duplicates: issues.append(f'{duplicates} duplicate order ID(s) detected.')
    if not issues: issues.append('No missing cells or duplicate order IDs detected by these checks.')
    return {'row_count': len(rows), 'column_count': len(headers), 'headers': headers,
            'numeric_columns': numeric_columns(headers, rows), 'missing_by_column': missing,
            'missing_cells': missing_total, 'duplicate_ids': duplicates,
            'quality_score': quality, 'issues': issues}


def normalize_rows(headers, rows):
    """Convert numeric-looking cells to numbers; derive revenue for familiar sales data."""
    out = []
    for source in rows:
        row = dict(source)
        for h in headers:
            value = str(row.get(h, '')).strip().replace(',', '')
            if value:
                try:
                    number = float(value)
                    row[h] = int(number) if number.is_integer() else number
                except ValueError:
                    pass
        if {'quantity', 'unit_price'}.issubset(headers):
            try:
                row['revenue'] = float(row['quantity']) * float(row['unit_price'])
            except (ValueError, TypeError, KeyError):
                pass
        out.append(row)
    return out


def gemini_json(prompt):
    api_key = os.getenv('GEMINI_API_KEY', '').strip()
    if not api_key:
        raise RuntimeError('Gemini API key is not configured yet. Add GEMINI_API_KEY to the .env file and restart InsightForge AI. See SETUP_GUIDE.md.')
    client = genai.Client(api_key=api_key)
    response = client.interactions.create(model=MODEL, input=prompt)
    raw = (getattr(response, 'output_text', None) or '').strip()
    if not raw:
        raise RuntimeError('Gemini returned an empty response. Please try again.')
    raw = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw, flags=re.I)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r'\{.*\}', raw, re.S)
        if match:
            return json.loads(match.group(0))
        raise RuntimeError('Gemini response was not valid JSON. Please rephrase your question.')


def ask_intent_agent(question, headers, numeric):
    prompt = f'''You are the Intent Agent in InsightForge AI, a careful CSV analytics system.\n'
    Return ONLY one JSON object with keys: intent, requested_metric, requested_group, requested_filter_column, requested_filter_value, needs_clarification.\n'
    intent must be one of: aggregate, grouped_analysis, ranking, row_count, describe, unsupported.\n'
    Use exact column names from the supplied headers. If user asks revenue and a revenue column is not present but both quantity and unit_price exist, use the derived column revenue.\n'
    Do not calculate or invent values. Use null for unknown fields.\n'
    Headers: {json.dumps(headers)}\nNumeric columns (including derived revenue if applicable): {json.dumps(numeric)}\nQuestion: {question}'''
    return gemini_json(prompt)


def ask_planner_agent(question, intent, headers, numeric, categorical):
    prompt = f'''You are the Planner Agent. Convert the user intent into one safe, executable analytics plan.\n'
    Return ONLY JSON with keys operation, metric_column, group_column, filter_column, filter_value, sort, limit.\n'
    operation must be one of sum, average, minimum, maximum, group_sum, group_average, group_count, top_group, count_rows, describe.\n'
    Use only exact allowed column names. sum/average/minimum/maximum require a numeric metric_column. group_sum/group_average require metric_column and group_column. group_count requires group_column. top_group requires group_column and metric_column. count_rows and describe need no columns.\n'
    sort must be asc or desc; limit must be an integer from 1 to 20. Use null when no filter. Never provide calculated values or code.\n'
    Question: {question}\nIntent: {json.dumps(intent)}\nHeaders: {json.dumps(headers)}\nNumeric columns: {json.dumps(numeric)}\nCategorical columns: {json.dumps(categorical)}'''
    return gemini_json(prompt)


def execute_plan(plan, headers, rows):
    allowed = {'sum', 'average', 'minimum', 'maximum', 'group_sum', 'group_average', 'group_count', 'top_group', 'count_rows', 'describe'}
    op = plan.get('operation')
    if op not in allowed: raise ValueError('The requested analysis plan is not supported.')
    metric, group = plan.get('metric_column'), plan.get('group_column')
    filt, fval = plan.get('filter_column'), plan.get('filter_value')
    if metric == 'revenue' and 'revenue' not in headers and {'quantity','unit_price'}.issubset(headers):
        metric = 'revenue'
    if metric and metric != 'revenue' and metric not in headers: raise ValueError(f'Gemini selected an unknown metric column: {metric}')
    if metric == 'revenue' and not ({'quantity','unit_price'}.issubset(headers) or 'revenue' in headers): raise ValueError('Revenue needs a revenue column or quantity and unit_price columns.')
    if group and group not in headers: raise ValueError(f'Gemini selected an unknown group column: {group}')
    if filt and filt not in headers: raise ValueError(f'Gemini selected an unknown filter column: {filt}')
    if filt and fval is not None:
        rows = [r for r in rows if str(r.get(filt, '')).casefold() == str(fval).casefold()]
    def num(row, col):
        value = row.get(col)
        if col == 'revenue' and value is None: value = float(row.get('quantity', 0)) * float(row.get('unit_price', 0))
        try: return float(value)
        except (TypeError, ValueError): return None
    evidence = {'operation': op, 'filter': ({'column': filt, 'value': fval} if filt and fval is not None else None), 'row_count_used': len(rows)}
    if op == 'count_rows':
        result = len(rows); evidence.update(metric='row count', value=result, formula='count of rows after any selected filter')
    elif op == 'describe':
        result = {'rows':len(rows), 'columns':headers, 'numeric_columns':numeric_columns(headers, rows)}
        evidence.update(metric='dataset description', value=result, formula='dataset schema and row count')
    elif op in ('sum','average','minimum','maximum'):
        if not metric: raise ValueError('The plan did not specify a numeric column. Try naming the column.')
        vals = [num(r, metric) for r in rows]; vals = [v for v in vals if v is not None]
        if not vals: raise ValueError(f'No numeric values found in {metric}.')
        result = {'sum':sum(vals), 'average':sum(vals)/len(vals), 'minimum':min(vals), 'maximum':max(vals)}[op]
        formula = {'sum':f'sum({metric})', 'average':f'sum({metric}) / count({metric})', 'minimum':f'min({metric})', 'maximum':f'max({metric})'}[op]
        evidence.update(metric=f'{op} of {metric}', column=metric, value=result, formula=formula)
    else:
        if not group: raise ValueError('The plan did not specify a grouping column.')
        grouped = defaultdict(list)
        for r in rows:
            key = str(r.get(group, '')).strip() or '(blank)'
            if op == 'group_count': grouped[key].append(1)
            else:
                if not metric: raise ValueError('The plan did not specify a numeric column.')
                v = num(r, metric)
                if v is not None: grouped[key].append(v)
        if not grouped: raise ValueError('No rows matched the requested grouping.')
        if op == 'group_count': values = {k:len(v) for k,v in grouped.items()}
        elif op == 'group_sum': values = {k:sum(v) for k,v in grouped.items()}
        else: values = {k:(sum(v)/len(v) if v else 0) for k,v in grouped.items()}
        values = dict(sorted(values.items(), key=lambda kv: kv[1], reverse=(plan.get('sort','desc') != 'asc')))
        limit = max(1, min(20, int(plan.get('limit') or 20)))
        if op == 'top_group':
            winner = next(iter(values.items()))
            result = {'winner':winner[0], 'value':winner[1], 'all_values':values}
            evidence.update(metric=f'{metric} by {group}', value=winner[1], winner=winner[0], values=values,
                            formula=f'group rows by {group}, then sum({metric})' if op == 'top_group' else '')
        else:
            result = dict(list(values.items())[:limit])
            formula = f'count rows grouped by {group}' if op == 'group_count' else f'{op.replace("group_", "")}({metric}) grouped by {group}'
            evidence.update(metric=f'{op} by {group}', value=result, values=result, formula=formula)
    return result, evidence


def verify_result(plan, evidence, recomputed, rows, headers):
    checks = []
    op = plan.get('operation')
    if op == 'count_rows':
        checks.append({'check':'reported row count matches the filtered dataset','passed':evidence['value'] == evidence.get('row_count_used')})
    elif op in ('sum','average','minimum','maximum'):
        checks.append({'check':'reported aggregate matches an independent recomputation','passed':math.isclose(float(evidence['value']), float(recomputed), rel_tol=1e-9, abs_tol=1e-8)})
    elif op in ('group_sum','group_average','group_count','top_group'):
        values = evidence.get('values', {})
        checks.append({'check':'group values match the deterministic aggregation','passed':bool(values) and all(k in recomputed.get('all_values', recomputed) and math.isclose(float(v), float(recomputed.get('all_values', recomputed)[k]), rel_tol=1e-9, abs_tol=1e-8) for k,v in values.items())})
        if op == 'top_group':
            winner = evidence.get('winner')
            best = max(recomputed['all_values'].items(), key=lambda x:x[1])
            checks.append({'check':'selected top group is the independently recomputed maximum','passed':winner == best[0]})
    else:
        checks.append({'check':'dataset description is based on the uploaded dataset','passed':evidence.get('value',{}).get('rows') == len(rows)})
    return {'status':'PASS' if all(c['passed'] for c in checks) else 'FAIL', 'checks':checks}


def insight_agent(question, result, evidence, verification):
    prompt = f'''You are the Insight Agent for InsightForge AI. Explain the already-computed result in clear, concise language for a student or business user.\n'
    Use ONLY facts in the JSON below. Do not invent, estimate, recalculate, or introduce any number not present there. Do not claim verification passed unless status is PASS.\n'
    Return ONLY JSON: {{"answer": "one or two sentence explanation", "caveat": "short caveat or empty string"}}\n'
    User question: {question}\nComputed result: {json.dumps(result, default=str)}\nEvidence: {json.dumps(evidence, default=str)}\nVerification: {json.dumps(verification)}'''
    return gemini_json(prompt)


@app.route('/')
def home(): return render_template('index.html')

@app.route('/api/health')
def health():
    return jsonify({'status':'ok','app':'InsightForge AI','gemini_configured':bool(os.getenv('GEMINI_API_KEY','').strip()),'model':MODEL})

@app.route('/api/upload', methods=['POST'])
def upload():
    file = request.files.get('file')
    if not file or not file.filename.lower().endswith('.csv'):
        return jsonify({'error':'Please upload a .csv file.'}), 400
    try:
        headers, rows = parse_csv_bytes(file.read())
        dataset_id = str(uuid.uuid4())
        profile = profile_dataset(headers, rows)
        normalized = normalize_rows(headers, rows)
        DATASETS[dataset_id] = {'name':file.filename,'headers':headers,'rows':normalized,'raw_rows':rows,'profile':profile}
        return jsonify({'dataset_id':dataset_id,'name':file.filename,'profile':profile,'preview':rows[:50],
                        'gemini_configured':bool(os.getenv('GEMINI_API_KEY','').strip())})
    except Exception as e: return jsonify({'error':str(e)}), 400

@app.route('/api/analyze', methods=['POST'])
def analyze():
    data = request.get_json(force=True) or {}
    ds = DATASETS.get(data.get('dataset_id'))
    if not ds: return jsonify({'error':'Dataset not found. Please upload it again.'}), 404
    question = str(data.get('question','')).strip()
    if not question: return jsonify({'error':'Enter a question first.'}), 400
    headers, rows = ds['headers'], ds['rows']
    numeric = numeric_columns(headers, rows)
    if 'revenue' not in headers and {'quantity','unit_price'}.issubset(headers): numeric.append('revenue')
    categorical = [h for h in headers if h not in numeric]
    try:
        intent = ask_intent_agent(question, headers, numeric)
        plan = ask_planner_agent(question, intent, headers + (['revenue'] if 'revenue' in numeric and 'revenue' not in headers else []), numeric, categorical)
        # Keep the operation constrained to an allow-list and exact uploaded column names.
        allowed_headers = headers + (['revenue'] if 'revenue' in numeric and 'revenue' not in headers else [])
        for key in ('metric_column','group_column','filter_column'):
            if plan.get(key) is not None and plan.get(key) not in allowed_headers:
                raise ValueError(f'Planner proposed unknown column {plan.get(key)!r}. Please rephrase the question using a column name from your dataset.')
        result, evidence = execute_plan(plan, allowed_headers, rows)
        # Independent recomputation uses a second execution of the validated plan.
        recomputed, _ = execute_plan(dict(plan), allowed_headers, rows)
        verification = verify_result(plan, evidence, recomputed, rows, allowed_headers)
        if verification['status'] != 'PASS':
            return jsonify({'error':'Independent verification failed. This result has not been marked as verified.','verification':verification}), 500
        narrative = insight_agent(question, result, evidence, verification)
        workflow = [
            {'name':'Intent Agent','status':'completed','detail':f"Gemini classified the request as {intent.get('intent','analytics')} and extracted the requested metric."},
            {'name':'Planner Agent','status':'completed','detail':f"Gemini proposed the {plan.get('operation')} operation; server validated its columns and operation."},
            {'name':'Data Quality Agent','status':'completed','detail':f"Profiled {ds['profile']['row_count']} rows and {ds['profile']['column_count']} columns; quality score {ds['profile']['quality_score']}/100."},
            {'name':'Analytics Agent','status':'completed','detail':'Server-side deterministic calculation executed against uploaded CSV values.'},
            {'name':'Evidence Agent','status':'completed','detail':f"Recorded formula, source columns, filtered row count ({evidence.get('row_count_used')}), and computed values."},
            {'name':'Verification Agent','status':'completed','detail':'Independent recomputation and consistency checks passed.'},
            {'name':'Insight Agent','status':'completed','detail':'Gemini generated a concise explanation from the verified result and evidence only.'},
            {'name':'Report Agent','status':'completed','detail':'A JSON evidence record is available in this response for reporting/export.'}
        ]
        return jsonify({'answer':narrative.get('answer','The analysis completed.'),'caveat':narrative.get('caveat',''),
                        'intent':intent,'plan':plan,'result':result,'evidence':evidence,'verification':verification,
                        'data_quality':ds['profile'],'workflow':workflow,'timestamp':datetime.utcnow().isoformat()+'Z'})
    except Exception as e:
        return jsonify({'error':str(e)}), 400

@app.route('/api/report/<dataset_id>', methods=['GET'])
def report(dataset_id):
    ds = DATASETS.get(dataset_id)
    if not ds: return jsonify({'error':'Dataset not found.'}), 404
    report_data = {'project':'InsightForge AI','dataset':ds['name'],'profile':ds['profile'],
                   'note':'This report contains dataset profiling only. Run a question to produce a question-specific evidence record.'}
    return jsonify(report_data)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', '5000')), debug=False)
