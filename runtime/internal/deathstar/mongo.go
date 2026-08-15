package deathstar

import (
	"context"
	"errors"

	"go.mongodb.org/mongo-driver/v2/bson"
	"go.mongodb.org/mongo-driver/v2/mongo"
)

type MongoStore struct {
	collection *mongo.Collection
}

func NewMongoStore(client *mongo.Client, database, collection string) (*MongoStore, error) {
	if client == nil || database == "" || collection == "" {
		return nil, errors.New("Mongo store requires a client, database, and collection")
	}
	return &MongoStore{collection: client.Database(database).Collection(collection)}, nil
}

// FindExact uses one aggregation so count and document evidence come from one
// MongoDB command. The facet returns the exact count but materializes at most
// one document, because any count other than one is deliberately inconclusive.
func (s *MongoStore) FindExact(ctx context.Context, query ReservationQuery) (QueryResult, error) {
	filter := bson.D{
		{Key: "customerName", Value: query.CustomerName},
		{Key: "hotelId", Value: query.HotelID},
		{Key: "inDate", Value: query.InDate},
		{Key: "outDate", Value: query.OutDate},
		{Key: "number", Value: query.Rooms},
	}
	pipeline := mongo.Pipeline{
		bson.D{{Key: "$match", Value: filter}},
		bson.D{{Key: "$facet", Value: bson.D{
			{Key: "metadata", Value: bson.A{bson.D{{Key: "$count", Value: "count"}}}},
			{Key: "facts", Value: bson.A{
				bson.D{{Key: "$limit", Value: 1}},
				bson.D{{Key: "$project", Value: bson.D{
					{Key: "_id", Value: 0}, {Key: "customerName", Value: 1},
					{Key: "hotelId", Value: 1}, {Key: "inDate", Value: 1},
					{Key: "outDate", Value: 1}, {Key: "number", Value: 1},
				}}},
			}},
		}}},
	}
	cursor, err := s.collection.Aggregate(ctx, pipeline)
	if err != nil {
		return QueryResult{}, err
	}
	defer cursor.Close(ctx)
	var rows []struct {
		Metadata []struct {
			Count int64 `bson:"count"`
		} `bson:"metadata"`
		Facts []ReservationFact `bson:"facts"`
	}
	if err := cursor.All(ctx, &rows); err != nil {
		return QueryResult{}, err
	}
	if len(rows) != 1 {
		return QueryResult{}, errors.New("Mongo observation aggregation returned no facet")
	}
	count := int64(0)
	if len(rows[0].Metadata) == 1 {
		count = rows[0].Metadata[0].Count
	} else if len(rows[0].Metadata) != 0 {
		return QueryResult{}, errors.New("Mongo observation aggregation returned invalid metadata")
	}
	if count == 1 {
		if len(rows[0].Facts) != 1 {
			return QueryResult{}, errors.New("Mongo observation aggregation omitted its unique fact")
		}
		return QueryResult{Count: count, Facts: rows[0].Facts}, nil
	}
	return QueryResult{Count: count}, nil
}
