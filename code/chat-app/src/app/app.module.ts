import { NgModule } from '@angular/core';
import { BrowserModule } from '@angular/platform-browser';
import { FormsModule } from '@angular/forms';
import { provideHttpClient, withInterceptorsFromDi, withXhr } from '@angular/common/http';

import { AppComponent } from './app.component';
import { ChatBoxComponent } from './chat-box/chat-box.component';
import { CacheViewComponent } from './cache-view/cache-view.component';

@NgModule({
  declarations: [
    AppComponent,
    ChatBoxComponent
  ],
  imports: [
    BrowserModule,
    FormsModule,
    CacheViewComponent
  ],
  providers: [
    provideHttpClient(withXhr(), withInterceptorsFromDi())
  ],
  bootstrap: [AppComponent]
})
export class AppModule { }
