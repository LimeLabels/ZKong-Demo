import { useState } from "react";
import Calendar from "react-calendar";
import "react-calendar/dist/Calendar.css";

interface Strategy {
  id: string;
  name: string;
  startDate: Date;
  endDate: Date;
  timeSlots: { start: string; end: string }[];
  products: { name: string; price: number }[];
}

export default function Dashboard() {
  const [selectedDate, setSelectedDate] = useState(new Date());
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [showCreateModal, setShowCreateModal] = useState(false);

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-7xl mx-auto py-8 px-4 sm:px-6 lg:px-8">
        <div className="mb-8">
          <h1 className="text-3xl font-bold text-gray-900">
            ZKong ESL Pricing Strategies
          </h1>
          <p className="mt-2 text-gray-600">
            Manage time-based pricing across all your integrations
          </p>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Calendar View */}
          <div className="lg:col-span-2">
            <div className="bg-white rounded-lg shadow p-6">
              <div className="flex justify-between items-center mb-6">
                <h2 className="text-xl font-semibold">Calendar</h2>
                <button
                  onClick={() => setShowCreateModal(true)}
                  className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
                >
                  Create Strategy
                </button>
              </div>
              <Calendar
                onChange={setSelectedDate}
                value={selectedDate}
                className="w-full"
              />

              {/* Strategies for selected date */}
              <div className="mt-6">
                <h3 className="text-lg font-medium mb-4">
                  Strategies on {selectedDate.toLocaleDateString()}
                </h3>
                {strategies.length === 0 ? (
                  <p className="text-gray-500">
                    No strategies scheduled for this date
                  </p>
                ) : (
                  <div className="space-y-3">
                    {strategies.map((strategy) => (
                      <div
                        key={strategy.id}
                        className="border rounded-lg p-4 hover:shadow-md transition"
                      >
                        <h4 className="font-semibold">{strategy.name}</h4>
                        <p className="text-sm text-gray-600">
                          {strategy.timeSlots
                            .map((slot) => `${slot.start} - ${slot.end}`)
                            .join(", ")}
                        </p>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Sidebar */}
          <div className="space-y-6">
            {/* Quick Stats */}
            <div className="bg-white rounded-lg shadow p-6">
              <h2 className="text-xl font-semibold mb-4">Quick Stats</h2>
              <div className="space-y-3">
                <div>
                  <p className="text-sm text-gray-600">Active Strategies</p>
                  <p className="text-2xl font-bold">{strategies.length}</p>
                </div>
              </div>
            </div>

            {/* Integrations */}
            <div className="bg-white rounded-lg shadow p-6">
              <h2 className="text-xl font-semibold mb-4">Integrations</h2>
              <div className="space-y-2">
                <div className="flex items-center justify-between p-2 rounded bg-green-50">
                  <span className="text-sm font-medium">Shopify</span>
                  <span className="text-xs text-green-600">Connected</span>
                </div>
                <div className="flex items-center justify-between p-2 rounded bg-gray-50">
                  <span className="text-sm font-medium">Square</span>
                  <span className="text-xs text-gray-400">Not Connected</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Create Strategy Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-6 max-w-2xl w-full mx-4 max-h-[90vh] overflow-y-auto">
            <h2 className="text-2xl font-bold mb-4">Create New Strategy</h2>
            <p className="text-gray-600 mb-6">
              Strategy creation form will be implemented here
            </p>
            <button
              onClick={() => setShowCreateModal(false)}
              className="px-4 py-2 bg-gray-200 rounded-lg hover:bg-gray-300"
            >
              Close
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
