// @vitest-environment jsdom
import {afterEach,it,expect,vi} from 'vitest';
import '@testing-library/jest-dom/vitest';
import {render,screen,cleanup} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import twin from '../fixtures/twin.json';
import positions from '../fixtures/positions.json';
import {MapView} from './map';
afterEach(cleanup);
it('keeps configured camera selection and explicit gaps usable without WebGL',async()=>{
  const select=vi.fn();
  render(<MapView twin={twin} positions={positions} time={15280} onCameraSelect={select}/>);
  expect(screen.getByRole('img',{name:'Property evidence map'})).toBeVisible();
  expect(screen.getAllByText('Not observed · 41 s').length).toBeGreaterThan(0);
  expect(screen.queryByLabelText('Current estimated position')).not.toBeInTheDocument();
  const button=screen.getByRole('button',{name:'Select Left passage'});
  await userEvent.click(button);expect(select).toHaveBeenCalledWith('side_left');
  expect(screen.getByText('Tree barrier',{selector:'span'})).toBeVisible();
});
