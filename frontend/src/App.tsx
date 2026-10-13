import { BrowserRouter, Navigate, Route, Routes } from 'react-router'

import { Layout } from '@/components/Layout'
import { CustomersPage } from '@/pages/CustomersPage'
import { InboxPage } from '@/pages/InboxPage'
import { InvoicesPage } from '@/pages/InvoicesPage'
import { IssuesPage } from '@/pages/IssuesPage'
import { OrdersPage } from '@/pages/OrdersPage'
import { PolicyPage } from '@/pages/PolicyPage'
import { StockPage } from '@/pages/StockPage'
import { UploadPage } from '@/pages/UploadPage'

// Each URL shows one page inside the shared Layout (header + navigation).
export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Navigate to="/upload" replace />} />
          <Route path="upload" element={<UploadPage />} />
          <Route path="inbox" element={<InboxPage />} />
          <Route path="orders" element={<OrdersPage />} />
          <Route path="invoices" element={<InvoicesPage />} />
          <Route path="policy" element={<PolicyPage />} />
          <Route path="stock" element={<StockPage />} />
          <Route path="customers" element={<CustomersPage />} />
          <Route path="issues" element={<IssuesPage />} />
          <Route path="*" element={<Navigate to="/upload" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
