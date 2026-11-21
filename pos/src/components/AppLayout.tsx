import { Navigate, Outlet } from 'react-router-dom';
import { useRootStore } from '../store/root-store';
import { canBill } from '../lib/billing';
import Header from './Header';
import Footer from './Footer';

const AppLayout = () => {
  const { user, posProfile } = useRootStore();

  // Captains never use the cashier shell: send them to the order screen.
  if (!canBill(user, posProfile)) {
    return <Navigate to="/order" replace />;
  }

  return (
    <div className="flex flex-col h-screen bg-gray-100 font-inter">
      <Header />
      <div className="flex-1 overflow-hidden">
        <Outlet />
      </div>
      <Footer />
    </div>
  );
};

export default AppLayout;
