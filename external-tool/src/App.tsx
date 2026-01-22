import { useState } from 'react'
import { Page, Layout, Tabs } from '@shopify/polaris'
import { ScheduleCalendar } from './components/ScheduleCalendar'
import { ScheduleList } from './components/ScheduleList'

function App() {
  const [selectedTab, setSelectedTab] = useState(0)

  const tabs = [
    {
      id: 'create',
      content: 'Create Schedule',
      panelID: 'create-panel',
    },
    {
      id: 'manage',
      content: 'Manage Schedules',
      panelID: 'manage-panel',
    },
  ]

  return (
    <Page title="Time-Based Pricing Schedules" fullWidth>
      <Tabs tabs={tabs} selected={selectedTab} onSelect={setSelectedTab}>
        <Layout>
          <Layout.Section>
            {selectedTab === 0 && <ScheduleCalendar />}
            {selectedTab === 1 && <ScheduleList />}
          </Layout.Section>
        </Layout>
      </Tabs>
    </Page>
  )
}

export default App
