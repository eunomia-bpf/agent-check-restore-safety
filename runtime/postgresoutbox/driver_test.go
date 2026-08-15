package postgresoutbox

import (
	"context"
	"errors"
	"strings"
	"testing"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/provideradapter"
	"github.com/jackc/pgx/v5"
)

const testOperationID = "op-0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"

func TestFactHashIsStableAndLengthFramed(t *testing.T) {
	got := FactHash(testOperationID, "application/json", []byte(`{"amount":7}`))
	const want = "ab63f010f7050cd12cb16cd2e99e5044aa55adee5f30eddca92662cf1fbc6bdb"
	if got != want {
		t.Fatalf("FactHash() = %q, want %q", got, want)
	}
	if got == FactHash(testOperationID, "application/jsonx", []byte(`{"amount":7}`)) ||
		got == FactHash(testOperationID, "application/json", []byte(`{"amount":8}`)) ||
		got == FactHash(testOperationID+"0", "application/json", []byte(`{"amount":7}`)) {
		t.Fatal("fact hash did not bind every field")
	}
	// These concatenations are identical without framing.
	if FactHash(testOperationID, "a", []byte("bc")) == FactHash(testOperationID, "ab", []byte("c")) {
		t.Fatal("fact hash is ambiguous across field boundaries")
	}
}

func TestRecordNormalizesAnEmptyBody(t *testing.T) {
	value := mustRecord(t, testOperationID, "", nil)
	if value.body == nil || len(value.body) != 0 {
		t.Fatalf("empty wire body was not normalized: %#v", value.body)
	}
}

func TestOpenDoesNotReturnAnInvalidDSN(t *testing.T) {
	const privateDSN = "postgres://adapter:do-not-return-this@host/%zz"
	_, err := Open(context.Background(), privateDSN)
	if err == nil {
		t.Fatal("invalid DSN was accepted")
	}
	if strings.Contains(err.Error(), privateDSN) || strings.Contains(err.Error(), "do-not-return-this") {
		t.Fatalf("Open() exposed a private DSN: %v", err)
	}
}

func TestExecuteInsertsWithDurabilitySettings(t *testing.T) {
	expected := mustRecord(t, testOperationID, "application/json", []byte(`{"amount":7}`))
	transaction := &fakeTransaction{inserted: true, insertedRecord: expected}
	database := &fakeDatabase{transaction: transaction}
	driver := &Driver{database: database}

	result, err := driver.Execute(context.Background(), provideradapter.Effect{
		OperationID: testOperationID, IdempotencyKey: testOperationID,
		ContentType: expected.contentType, Body: expected.body,
	})
	if err != nil {
		t.Fatal(err)
	}
	assertSuccess(t, result, expected)
	assertEvents(t, transaction.events, "synchronous_commit", "insert", "commit")
	if transaction.rolledBack {
		t.Fatal("committed transaction was rolled back")
	}
}

func TestExecuteReadsExistingRowInSecondStatement(t *testing.T) {
	expected := mustRecord(t, testOperationID, "application/json", []byte(`{"amount":7}`))
	transaction := &fakeTransaction{inserted: false, lookupRecord: expected}
	driver := &Driver{database: &fakeDatabase{transaction: transaction}}

	result, err := driver.Execute(context.Background(), provideradapter.Effect{
		OperationID: testOperationID, IdempotencyKey: testOperationID,
		ContentType: expected.contentType, Body: expected.body,
	})
	if err != nil {
		t.Fatal(err)
	}
	assertSuccess(t, result, expected)
	assertEvents(t, transaction.events, "synchronous_commit", "insert", "lookup", "commit")
}

func TestExecuteRejectsConflictWithoutFalseFailure(t *testing.T) {
	expected := mustRecord(t, testOperationID, "application/json", []byte(`{"amount":7}`))
	other := mustRecord(t, testOperationID, "application/json", []byte(`{"amount":8}`))
	transaction := &fakeTransaction{lookupRecord: other}
	driver := &Driver{database: &fakeDatabase{transaction: transaction}}

	result, err := driver.Execute(context.Background(), provideradapter.Effect{
		OperationID: testOperationID, IdempotencyKey: testOperationID,
		ContentType: expected.contentType, Body: expected.body,
	})
	if !errors.Is(err, ErrConflict) {
		t.Fatalf("Execute() error = %v, want ErrConflict", err)
	}
	if result.Outcome == provideradapter.Failed {
		t.Fatal("conflict was represented as a false failed outcome")
	}
	if transaction.committed || !transaction.rolledBack {
		t.Fatalf("conflicting transaction state: committed=%v rolledBack=%v", transaction.committed, transaction.rolledBack)
	}
}

func TestExecuteRejectsCorruptStoredRow(t *testing.T) {
	expected := mustRecord(t, testOperationID, "application/json", []byte(`{"amount":7}`))
	corrupt := expected
	corrupt.factHash = strings.Repeat("0", 64)
	transaction := &fakeTransaction{lookupRecord: corrupt}
	driver := &Driver{database: &fakeDatabase{transaction: transaction}}

	result, err := driver.Execute(context.Background(), provideradapter.Effect{
		OperationID: testOperationID, IdempotencyKey: testOperationID,
		ContentType: expected.contentType, Body: expected.body,
	})
	if !errors.Is(err, ErrCorruptRecord) {
		t.Fatalf("Execute() error = %v, want ErrCorruptRecord", err)
	}
	if result.Outcome == provideradapter.Failed {
		t.Fatal("corruption was represented as a false failed outcome")
	}
}

func TestObserveMissingIsInconclusive(t *testing.T) {
	driver := &Driver{database: &fakeDatabase{lookupErr: pgx.ErrNoRows}}
	result, err := driver.Observe(context.Background(), provideradapter.Query{
		OperationID: testOperationID, RequestHash: strings.Repeat("a", 64),
		ContentType: "application/json", Body: []byte(`{"amount":7}`),
	})
	if err != nil {
		t.Fatal(err)
	}
	if result != (provideradapter.Result{Outcome: provideradapter.Inconclusive}) {
		t.Fatalf("Observe() = %+v, want bare inconclusive result", result)
	}
}

func TestExecuteAndObserveReturnSameFact(t *testing.T) {
	expected := mustRecord(t, testOperationID, "application/json", []byte(`{"amount":7}`))
	transaction := &fakeTransaction{inserted: true, insertedRecord: expected}
	database := &fakeDatabase{transaction: transaction, lookupRecord: expected}
	driver := &Driver{database: database}

	direct, err := driver.Execute(context.Background(), provideradapter.Effect{
		OperationID: testOperationID, IdempotencyKey: testOperationID,
		ContentType: expected.contentType, Body: expected.body,
	})
	if err != nil {
		t.Fatal(err)
	}
	observed, err := driver.Observe(context.Background(), provideradapter.Query{
		OperationID: testOperationID, RequestHash: strings.Repeat("a", 64),
		ContentType: expected.contentType, Body: expected.body,
	})
	if err != nil {
		t.Fatal(err)
	}
	if direct != observed {
		t.Fatalf("direct result %+v differs from observed result %+v", direct, observed)
	}
}

func TestObserveConflictAndCorruptionAreErrors(t *testing.T) {
	expected := mustRecord(t, testOperationID, "application/json", []byte(`{"amount":7}`))
	other := mustRecord(t, testOperationID, "application/json", []byte(`{"amount":8}`))
	driver := &Driver{database: &fakeDatabase{lookupRecord: other}}
	result, err := driver.Observe(context.Background(), provideradapter.Query{
		OperationID: testOperationID, RequestHash: strings.Repeat("a", 64),
		ContentType: expected.contentType, Body: expected.body,
	})
	if !errors.Is(err, ErrConflict) {
		t.Fatalf("Observe() error = %v, want ErrConflict", err)
	}
	if result.Outcome == provideradapter.Failed {
		t.Fatal("observation conflict was represented as failed")
	}

	corrupt := expected
	corrupt.bodyHash = strings.Repeat("0", 64)
	driver = &Driver{database: &fakeDatabase{lookupRecord: corrupt}}
	_, err = driver.Observe(context.Background(), provideradapter.Query{
		OperationID: testOperationID, RequestHash: strings.Repeat("a", 64),
		ContentType: expected.contentType, Body: expected.body,
	})
	if !errors.Is(err, ErrCorruptRecord) {
		t.Fatalf("Observe() corruption error = %v, want ErrCorruptRecord", err)
	}
}

func TestExecuteRequiresMatchingIdempotencyIdentity(t *testing.T) {
	driver := &Driver{database: &fakeDatabase{}}
	_, err := driver.Execute(context.Background(), provideradapter.Effect{
		OperationID: testOperationID, IdempotencyKey: "different",
	})
	if err == nil {
		t.Fatal("mismatched idempotency identity was accepted")
	}
}

func TestValidatePhysicalConnection(t *testing.T) {
	tests := []struct {
		name      string
		values    []bool
		wantError string
	}{
		{name: "valid", values: []bool{true, true, true, true}},
		{name: "standby", values: []bool{false, true, true, true}, wantError: "primary"},
		{name: "fsync disabled", values: []bool{true, false, true, true}, wantError: "fsync=on"},
		{name: "full page writes disabled", values: []bool{true, true, false, true}, wantError: "full_page_writes=on"},
		{name: "table absent or unlogged", values: []bool{true, true, true, false}, wantError: tableName},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			connection := &fakeConnection{row: &boolRow{values: test.values}}
			err := validatePhysicalConnection(context.Background(), connection)
			if test.wantError == "" && err != nil {
				t.Fatal(err)
			}
			if test.wantError != "" && (err == nil || !strings.Contains(err.Error(), test.wantError)) {
				t.Fatalf("error = %v, want text %q", err, test.wantError)
			}
			if connection.query != connectionInvariantSQL {
				t.Fatal("connection invariant query changed")
			}
		})
	}
}

func mustRecord(t *testing.T, operationID, contentType string, body []byte) record {
	t.Helper()
	value, err := recordFor(operationID, contentType, body)
	if err != nil {
		t.Fatal(err)
	}
	return value
}

func assertSuccess(t *testing.T, result provideradapter.Result, expected record) {
	t.Helper()
	if result.Outcome != provideradapter.Succeeded || result.FactHash != expected.factHash ||
		result.RemoteReference != remoteReferenceV1+expected.operationID {
		t.Fatalf("result = %+v, want durable success for %+v", result, expected)
	}
}

func assertEvents(t *testing.T, got []string, want ...string) {
	t.Helper()
	if strings.Join(got, ",") != strings.Join(want, ",") {
		t.Fatalf("transaction events = %v, want %v", got, want)
	}
}

type fakeDatabase struct {
	transaction  *fakeTransaction
	beginErr     error
	lookupRecord record
	lookupErr    error
	closed       bool
}

func (database *fakeDatabase) beginExecute(context.Context) (executeTransaction, error) {
	if database.beginErr != nil {
		return nil, database.beginErr
	}
	if database.transaction == nil {
		return nil, errors.New("unexpected transaction")
	}
	return database.transaction, nil
}

func (database *fakeDatabase) lookup(context.Context, string) (record, error) {
	return database.lookupRecord, database.lookupErr
}

func (database *fakeDatabase) close() {
	database.closed = true
}

type fakeTransaction struct {
	events         []string
	inserted       bool
	insertedRecord record
	insertErr      error
	lookupRecord   record
	lookupErr      error
	setErr         error
	commitErr      error
	committed      bool
	rolledBack     bool
}

func (transaction *fakeTransaction) setSynchronousCommit(context.Context) error {
	transaction.events = append(transaction.events, "synchronous_commit")
	return transaction.setErr
}

func (transaction *fakeTransaction) insert(context.Context, record) (record, bool, error) {
	transaction.events = append(transaction.events, "insert")
	return transaction.insertedRecord, transaction.inserted, transaction.insertErr
}

func (transaction *fakeTransaction) lookup(context.Context, string) (record, error) {
	transaction.events = append(transaction.events, "lookup")
	return transaction.lookupRecord, transaction.lookupErr
}

func (transaction *fakeTransaction) commit(context.Context) error {
	transaction.events = append(transaction.events, "commit")
	transaction.committed = transaction.commitErr == nil
	return transaction.commitErr
}

func (transaction *fakeTransaction) rollback(context.Context) error {
	transaction.events = append(transaction.events, "rollback")
	transaction.rolledBack = true
	return nil
}

type fakeConnection struct {
	row   pgx.Row
	query string
}

func (connection *fakeConnection) QueryRow(_ context.Context, query string, _ ...any) pgx.Row {
	connection.query = query
	return connection.row
}

type boolRow struct {
	values []bool
	err    error
}

func (row *boolRow) Scan(destinations ...any) error {
	if row.err != nil {
		return row.err
	}
	if len(destinations) != len(row.values) {
		return errors.New("unexpected destination count")
	}
	for index, value := range row.values {
		pointer, ok := destinations[index].(*bool)
		if !ok {
			return errors.New("unexpected destination type")
		}
		*pointer = value
	}
	return nil
}
